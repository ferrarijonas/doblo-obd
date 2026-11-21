# Doblò 2016 + ELM327 — o que foi aprendido na prática

Registro técnico da sessão de 18/11/2026, com os valores exatos medidos no carro.
Serve para não repetirmos os mesmos erros e para qualquer diagnóstico futuro.

---

## 1. O carro

**Fiat Doblò Adventure 2016** — nacional, plataforma 178/263, 1.8 E.torQ 16v flex,
130/132 cv, câmbio manual C510 de 5 marchas, 6 lugares, injeção multiponto
Magneti Marelli. Tomada OBD à esquerda da coluna de direção, junto à caixa de
fusíveis.

### Protocolo (medido, não presumido)

```
ATSP0 + 0100  ->  4100BE3EB811   |  ATDPN -> A5
```

**KWP 2000 fast (ISO 14230-4) na K-line, pino 7.** Não é CAN. Isso contrariou a
suposição inicial (todo carro 2016 seria CAN 11/500) e custou horas de teste
errado. Forçar `ATSP6` devolve `CAN ERROR` — a central nem tem CAN no pino 6/14.

### PIDs realmente suportados (`4100BE3EB811`)

`01, 03, 04, 05, 06, 07, 0B, 0C, 0D, 0E, 0F, 11, 13, 14, 15, 1C, 20, 21`

| PID | Nome | Observação |
|---|---|---|
| 01 | MIL + nº de falhas | funciona |
| 03 | status do combustível | funciona |
| 04 | carga do motor | ~2,7 % em marcha lenta |
| 05 | temp. do motor | 88–99 °C |
| 06/07 | trims | **escala não confiável neste ECU** (ver §7) |
| 0B | MAP | 31 kPa em marcha lenta, 90 kPa motor parado |
| 0C | RPM | 795–805 em marcha lenta |
| 0D | velocidade | ok |
| 0E | avanço | ok |
| 0F | temp. do ar | 61–62 °C com motor quente parado |
| 11 | acelerador | 13–17 % |
| 13 | sondas presentes | `03` = 2 sondas (banco 1, antes e depois do catalisador) |
| 14/15 | tensão das sondas | 0,0–1,0 V, oscilando = sonda viva |
| 1C | padrão OBD | ok |
| 20/21 | PIDs 21-40, distância com MIL | `0121 -> 0002` = 2 km |

**Não existem nesta central:** MAF (10), nível de combustível (2F), vazão (5E),
031/032/033 (aquecimentos, baro), 1F (tempo de motor), 30/31/3C/3D/42/46.
**Modo 09 (VIN) não é implementado** — por isso o painel mostra `-`.

---

## 2. O adaptador

`ELM327 v2.1` clone Bluetooth clássico, **38400 baud**, pareado como `OBDII`
(MAC `01:23:45:67:89:BA`), porta **COM8** no Windows.

### Pegadinhas encontradas

- **Pareamento exige PIN** (`1234`). `PairAsync(None)` do WinRT falha; o handler
  de PIN via scriptblock no PowerShell 5.1 não executa (sem runspace) e retorna
  `RejectedByHandler`. Solução: parear pela UI do Windows.
- O Windows **cria a porta COM só depois do pareamento**. Antes disso o erro é
  `ERROR_SEM_TIMEOUT (121)` ao abrir — não é defeito do adaptador.
- **Porta COM Bluetooth fica presa ~5–15 s no fechamento.** Cada teste one-shot
  deixava processo pendurado e o próximo abria com `PermissionError 13`.
  Conclusão prática: um processo só, dono da porta, como o app faz.
- **`ATDPN` volta vazio** quando o protocolo é forçado (`ATSP5`). O app usa
  fallback pelo protocolo que conseguiu falar.
- **`ATMA` (monitor do barramento) não existe** nesse clone — retorna `?`.
- `ATRV` reporta **16,5 V** com bateria normal. ADC do clone descalibrado; não
  use essa leitura para diagnóstico elétrico.
- No primeiro `0100` o ELM emite `BUS INIT:...` antes da resposta. O app faz
  `reset_input_buffer()` a cada comando, então isso é descartado sem problema.

### O que NÃO era o problema

Testado e descartado, com a chave em ON e com o motor ligado:

| Teste | Resultado |
|---|---|
| `ATSP3` ISO 9141 | `BUS INIT: . . . UNABLE TO CONNECT` |
| `ATSP4` KWP 5 baud | `UNABLE TO CONNECT` |
| `ATSP5` KWP fast | **funciona** |
| `ATSP6/7/8` CAN | `UNABLE TO CONNECT` / `CAN ERROR` |
| `3E00` direto no 7E0 | `UNABLE TO CONNECT` |
| 9600 baud | sem resposta |

O auto-search (`ATSP0`) levava 4,4 s e às vezes desistia antes do init de 5 baud —
por isso o app **fixa `ATSP5`** e só cai para auto se não houver resposta.

---

## 3. Bug que travou o app (corrigido)

`Elm.supported()` devolve números de PID sem o byte de modo (`0x0C`), mas o filtro
comparava com `int("010C", 16)` = **268**. Nunca casava → lista de sensores vazia
→ app dizia "adaptador respondeu, mas o carro não" mesmo com o carro respondendo.

Correção: `int(s[1][2:], 16)`. Coberto por assert no `--selftest`.

---

## 4. O app

`obd_doblo.py` — arquivo único, só `pyserial`.

```
python obd_doblo.py --port COM8      # no carro
python obd_doblo.py --demo           # sem carro
python obd_doblo.py --selftest       # decodificadores + parser com ELM falso
python obd_doblo.py --list           # portas COM
```

Painel em `http://127.0.0.1:8770`.

- Loop: 4 sensores rápidos (RPM, velocidade, acelerador, carga) a cada ciclo;
  os lentos (temperaturas, MAP, trims, avanço) a cada 5 ciclos. Ciclo ≈ 0,5 s.
- Thread única dona da serial + `LOCK`, porque K-line é half-duplex.
- CSV em `logs/viagem-AAAAMMDD-HHMMSS.csv`, UTF-8 com BOM, uma linha por ciclo,
  flush a cada linha.
- Endpoints: `/api/state`, `/api/pids` (varredura completa), `/api/dtc/read`,
  `/api/dtc/clear`, `/api/log`.

### CLIs de diagnóstico usadas na sessão (apagadas depois)

Probe one-shot, varredura de protocolos, dump cru com timestamp, teste de
keep-alive. Ficaram de fora do repo de propósito — a porta fica presa e só
atrapalha. Duas que valem lembrar:

- **`01` + PID retorna `41` + PID + dados.** `pid()` valida o prefixo, então
  resposta de outro PID não contamina.
- **Freeze frame é `02` + PID + `00`** (ex.: `020C00` = RPM no momento da falha).

---

## 5. Histórico de diagnóstico — P1220

Leitura crua: `03 -> 43122000000000` → **P1220**. MIL aceso (`0101 -> 81`),
1 código, **nenhum pendente** (`07 -> 47...`).

Freeze frame (`02xx00`) — condições no instante em que a central gravou:

| Campo | Valor | Leitura |
|---|---|---|
| DTC | `1220` | o próprio P1220 |
| RPM | 855 | marcha lenta |
| velocidade | **0 km/h** | **parado** |
| temp. motor | 88 °C | motor quente |
| carga | 5,9 % | sem carga |
| MAP | 42 kPa | vácuo de marcha lenta normal |
| acelerador / avanço | não suportados no frame | `7F0212` |

`0121 -> 0002` → **MIL aceso há 2 km** (falha recente).
`0130/0131/011F` → `7F0112` (não suportados).
`0600 -> 4600FF00000001` indica testes de bordo, mas **todo TID 01–0F responde
`7F0612`**: não há contador de misfire legível. Não dá para medir falha de
vela/bobina por aqui.

### Interpretação

P1220 na Fiat = sinal de posição do acelerador/borboleta implausível. No Doblò o
acelerador é eletrônico: pedal (2 sensores) → chicote/conector → corpo de
borboleta motorizado. É código de **circuito**, não de peça mecânica.

**O MIL apagou sozinho** entre 20:55 e 21:10: `0101` passou de `81 05 61 00`
(MIL aceso, 1 falha) para `01 05 61 00` (luz apagada, 1 falha ainda gravada).
Ou seja, a central não repetiu a falha no ciclo seguinte e apagou a luz, mas
manteve o código — comportamento normal de "falha não confirmada novamente".
`0121 -> 0002` segue indicando que a luz ficou 2 km acesa.

Isso é bom sinal: o defeito não se repetiu na partida seguinte. Se voltar ao
andar, aí sim é intermitente de verdade.

**Nada foi apagado.** O app só envia `04` (limpar) dentro de `clear_dtcs()`,
alcançável apenas pelo `POST /api/dtc/clear`, que a UI dispara só no botão
"apagar falhas" (com `confirm()`). Provas de que não houve clear: `03` continua
devolvendo `431220` e `0121` ainda marca 2 km — limpar zera os dois e apaga o
freeze frame. O que mudou foi só o bit do MIL em `0101` (`81` → `01`).

Contexto do dono: pegou ruas alagadas quando acendeu; a esposa relatou o carro
"falhando" dias antes. O conector do pedal fica rente ao assoalho — água/oxidação
ali é causa clássica. Sinal intermitente explica hesitação antes do código.

O freeze frame mostra 0 km/h: a falha foi *confirmada* com o carro parado, motor
quente — compatível com parar logo depois do trecho alagado.

### O que ainda não se sabe

Se o código voltar depois de secar/limpar o conector do pedal e o corpo de
borboleta, aí é sensor/pedal. Sem limpeza prévia, trocar peça é chute.

---

## 6. Sondas lambda (última leitura)

```
0113 -> 03      duas sondas presentes
0114 -> varia  0x00 .. 0xFF  (0,0 .. 1,0 V)
0115 -> 0x00/0x8E
```

Sonda 1 oscilando entre pobre e rico = **sinal vivo, central em malha fechada**.
Isso afasta sonda morta, mas não afasta entrada de ar falsa.

---

## 7. O que NÃO é confiável neste carro

Registrado para ninguém repetir a conclusão errada que eu tirei no meio da sessão.

- **STFT/LTFT (PIDs 06/07)** — os cards `STFT*` e `LTFT*` do painel: com motor
  ligado, o byte oscilou de `0x03` a `0xFE` em 2 s — o que daria −98 % a +84 % de
  correção. Não é trim real nessa escala (±25 % é o normal). O LTFT fica cravado
  em `0x23`. **Não use para diagnóstico.**
- **`ATRV`**: lê 16,5 V num sistema de 12 V. Ignore.
- **VIN**: modo 09 não implementado.
- **Contadores de misfire**: modo 06 não implementado.
- **Distância desde apagar códigos / tempo de motor**: PIDs não suportados.

---

## 8. Comparação com apps tipo "Infocar"/Torque

Eles parecem mostrar "muito mais" porque listam **todo PID respondido**, inclusive
os que não viram mostrador (status de combustível, presença de sondas, padrão OBD,
distância com MIL). Nesta central são 19 PIDs — a varredura completa está no botão
**"todos os PIDs"** do painel. Não existe PID escondido além desses: a lista de
suporte (`0100/0120/0140/0160`) é a fonte da verdade.

Apps comerciais também leem PIDs **proprietários** (modo 22) via banco de dados da
fabricante — isso sim dá coisas como temperatura de câmbio e contadores internos,
e não é acessível por OBD genérico.

---

## 9. Próximos passos sugeridos

1. Secar/limpar o conector do pedal (assoalho, atrás do batente) e o do corpo de
   borboleta; limpar o corpo de borboleta.
2. Rodar o app numa volta de 10–15 min e comparar o freeze frame novo com o desta
   sessão (parado vs. andando).
3. Se P1220 voltar: sensor/pedal ou corpo de borboleta.
4. Se quiser acesso a ABS, airbag, body computer e painel: MultiEcuScan + cabo
   amarelo A3 (CAN de baixa velocidade nos pinos 1/9). O ELM327 sozinho não vê.

---

## 10. Painel e relógio — o que foi testado (18/11/2026)

### Varredura K-line: inconclusiva por limitação do adaptador

Tentativa 1: `ATSH 81 <end> F1` + KWP `81` (StartCommunication) em 0x01–0x7F.
Resultado: **todas as 127 respostas idênticas** — `83 F1 10 C1 E9 8F BD`
(origem `0x10` = motor, mesmas chaves). O `ATSH` foi ignorado.

Tentativa 2: `ATIIA <end>` + `ATSP5` + `ATSH`, validando o byte de origem.
Tentativa 3: idem com `ATPC` (protocol close) e com `ATZ` por endereço.

**Todas devolveram origem `0x10`.** Conclusão: este clone não endereça outros
ECUs na K-line. Não é prova de que só exista o motor no pino 7 — é o adaptador
que não sabe perguntar. Varredura fica pendente de hardware melhor
(KKL/VagCom 409, ou MES com o cabo certo).

### Onde o painel realmente está (fonte secundária)

Projeto **`fmntf/fiatcan`** (Doblò 263): a B-CAN fica nos **pinos 1/9, 50 kbit/s**;
a C-CAN (motor) em 6/14. IDs de 29 bits = 2 bytes de tópico + 2 de nó:

| Nó | ID |
|---|---|
| Body Computer | `0x4000` |
| **Instrument Panel** | `0x4003` |
| Rádio | `0x4005` |
| Blue&Me | `0x4021` |

O autor não usou a tomada OBD: interceptou o conector de 32 vias do Blue&Me.

**Frame do relógio, transmitido pelo painel a 1 Hz:**

```
0C214003#183810072019      ->  18:38  10/07/2019
```

Ou seja: a hora **existe na rede**, emitida pelo próprio painel. Ler é fácil com
um CAN de 50 kbit nos pinos 1/9. Escrever é outra história: o painel é o
*emissor*, então não basta reescrever o frame — é preciso achar o comando de
ajuste (provavelmente vindo do body computer ou do rádio).

### Limitações do nosso hardware para isso

- ELM327 só faz CAN 250/500 kbit (protocolos 6–9). **Não faz 50 kbit.**
- Os pinos 1/9 exigem cabo adaptador (o A3 do MES faz 6/14 → 1/9).
- Logo: para o B-CAN precisamos de outro hardware (CANable + cabo, ou MES + A3).

### Fontes conflitantes sobre ajustar a hora por diagnóstico

- Autor do MES (2010): "No, it is not possible to set date and time using
  Multiecuscan."
- Fórum fiat500owners (2016): relato de MES ajustando a hora de um 500 **com o
  adaptador amarelo**, válido só em painéis com "short menu".

Não testado no Doblò. Antes de assumir qualquer um dos dois, rodar o *Scan* do
MES e olhar a aba **Adjustments** do painel.

---

## 11. Serviços proprietários: não existem no ECU do motor (18/11/2026)

Testado no ECU do motor (`0x10`) na K-line, respostas cruas:

```
1081   -> 7F 10 11    StartDiagnosticSession: service not supported
1085   -> 7F 10 11
1A90   -> 7F 1A 11    readECUIdentification
2101   -> 7F 21 11    readDataByLocalIdentifier
2102   -> 7F 21 11
220001 -> 7F 22 11    readDataByIdentifier
```

Varredura de LIDs `0x01`–`0x9F` com `21`: **zero** respostas positivas.
(`0x11` = serviceNotSupported.)

**Conclusão:** essa central implementa **apenas os serviços OBD (modos 01–0A)**.
Não aceita sessão de diagnóstico, não tem identificação por `1A`, não tem
parâmetros proprietários. Os 19 PIDs do §1 são *tudo* o que ela expõe.

Consequências medidas:

- **Hodômetro não está no motor.** Está no painel, na B-CAN (§10).
- Os "2.000 sensores do fabricante" do app Infocar **não vêm deste ECU** — e não
  poderiam: o app fala ELM327 na tomada padrão, no mesmo barramento.
- Qualquer dado além dos 19 PIDs exige a **B-CAN** (pinos 1/9, 50 kbit) ou outro
  módulo acessível.

Isso encerra a ideia de "puxar mais dados direto do motor": não há o que puxar.

**Confirmação por força bruta (18/11/2026):** todos os PIDs 0x01–0x60 do modo
01 foram perguntados ignorando o bitmap. Responderam **exatamente** os do bitmap
(01, 03–0F, 11, 13, 14, 15, 1C, 20, 21). Os demais devolvem `7F 01 12`
(subFunctionNotSupported), incluindo os que os apps mostram em outros carros:

- `5C` temperatura do óleo → **não existe aqui**
- `0A`/`23`/`59` pressão de combustível → **não existe**
- `2F` nível de combustível, `33` barométrica, `46` ambiente, `5E` vazão,
  `62` torque, `63` pressão do óleo → **não existem**

Modos 05 (testes O2) e 08 (EVAP): `7F xx 12`, não existem.

**Modo 09 funciona parcialmente** — VIN e CalID sim, CVN/nome não:

```
0902 -> 490201 00000039 | 490202 42443131 | 490203 39343053 |
        490204 47313133 | 490205 34343538
       = "9BD11940SG1134458"   (posição 10 = 'G' = ano 2016 ✓)
0904 -> calibração "3032…" presente
0900 -> 49 00 01 F0 00 00 00  (tipos 01–F0)
```

O app passou a ler o VIN nesse formato multi-registro (testado em `--selftest`).

**Consequência para o mistério do Infocar:** com o mesmo adaptador na mesma
tomada, nenhum app consegue óleo/pressão desse carro — o ECU rejeita com
`7F 01 12`. O que aparecia no app era ou valor **estimado/rotulado** (ex.: MAP
de 31 kPa chamado de "pressão do motor", temp. do motor chamada de "óleo"), ou
perfil de outro veículo. Dado medido não é.

**Esgotamento final (18/11/2026, madrugada):**

- PIDs `0x61`–`0xFF` do modo 01 (fora do bitmap): **zero** respostas.
- Serviços KWP restantes (referência: enum da crate `automotive_diag` 0.1.29,
  out/2026, que é o que os projetos modernos implementam):

```
17 -> 7F 17 11   readStatusOfDTC            NAO EXISTE
18 -> 7F 18 11   readDTCByStatus            NAO EXISTE
23 -> 7F 23 11   readMemoryByAddress        NAO EXISTE
27 -> 7F 27 11   securityAccess             NAO EXISTE (nem seed)
2C -> 7F 2C 11   dynamicDefineLocalId       NAO EXISTE
0A -> 7F 0A 11   modo 0A (permanentes)      NAO EXISTE
```

Junto com `10/1A/21/22` já medidos, **todo serviço de leitura do KWP2000 está
ausente**. O repertório do ECU é exatamente: modos 01 (19 PIDs), 02 (freeze
frame), 03, 04, 07, 09 parcial (VIN + CalID). Não há canal para dado
proprietário neste ECU — qualquer ferramenta do planeta recebe o mesmo `7F xx 11`.

**IMPORTANTE — escopo desta conclusão:** ela vale para o **pino 7 (K-line) com
ELM327 genérico**. Fatos adicionais anotados na conversa com o dono (18/11/2026):

- **O Infocar foi usado com o MESMO ELM327** — logo, o app só alcançava o
  pino 7, o mesmo canal medido aqui. Qualquer valor que ele mostrou veio do
  modo 01 (os 19 PIDs) ou foi estimativa/rótulo.
- Os valores **mudavam** ao vivo → são PIDs reais (ex.: temp. do motor sobe com
  o aquecimento). Isso é consistente com "óleo" = rótulo do PID 05/0F.
- Teste decisivo pendente: carro frio, comparar lado a lado o "óleo" do Infocar
  com o "temp. motor" do nosso painel. Números iguais = mesmo PID.

O que **ainda não foi medido** neste carro (e pode ter dado proprietário):

1. **Pino 3** — segunda K-line (onde a Fiat pendura o airbag; o cabo A2 do MES
   mapeia pino 7 → pino 3 exatamente para isso). Precisa de cabo extensor com
   jumper — barato, pendente.
2. **Pinos 1/9 (B-CAN, 50 kbit)** — painel, body computer, rádio: onde estão
   relógio e provavelmente o hodômetro. Pendente de CANable/ESP32+MCP2515.
3. **Hardware proprietário** — o Infocar vende adaptador próprio ("otimizado
   para produtos proprietários"); se o dono usou esse adaptador, a pinagem pode
   alcançar módulos que o ELM327 genérico não vê. Perguntar ao dono qual
   adaptador usou.

E a questão física: **temperatura do óleo exige um sensor de óleo no motor**.
Se o E.torQ não tem o sensor (só a chave de pressão do painel), nenhum app
mostra valor real — é impossível por física, não por protocolo. Ainda não
confirmei se esse motor tem o sensor.
