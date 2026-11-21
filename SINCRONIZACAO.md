# Sincronização e memória — camada obrigatória

Especificação da parte do ESP32 que tira o dado do carro e o guarda.
Decidida em 18/11/2026, antes de existir firmware.

Regra que vale acima de todas: **a coleta nunca espera a rede.** Sincronizar é
oportunista; gravar é prioridade.

---

## 1. Redes, em ordem de tentativa

| # | Rede | Quando | Observação |
|---|---|---|---|
| 1 | Lista de SSIDs conhecidos (NVS) | boot | casa, trabalho, casa de parente, oficina |
| 2 | Hotspot do celular | boot, se cadastrado | consome dados móveis |
| 3 | AP próprio `DobloOBD` | fallback | você entra e abre `192.168.4.1` |

- Tenta cada SSID conhecido por até 8 s. Se nenhum associar, sobe o AP e começa
  a gravar.
- **Gravar nunca depende de ter rede.** Sem rede conhecida, o AP sobe e a coleta
  segue normal.
- O AP próprio é senha fixa no firmware, não rede aberta.

## 2. Quando sincroniza

| Janela | Duração | Comportamento |
|---|---|---|
| Boot (chave ON) | até ~30 s | envia pendentes **antes** de abrir o Bluetooth |
| Manual | — | botão "sincronizar agora" na página |
| Nunca | — | não existe janela com o carro desligado (a chave corta a energia) |

Não sincroniza em paralelo com o polling: no ESP32 o WiFi e o Bluetooth clássico
dividem o mesmo rádio e um degrada o outro. Envia primeiro, depois começa a ler.

Se os 30 s acabarem no meio, o envio **retoma na próxima partida** do byte onde
parou — nunca recomeça do zero.

## 3. Protocolo

Um arquivo por viagem. Nada de stream contínuo.

O destino é **o Google Drive, direto do ESP32**. Não existe receptor no notebook.

```
POST https://script.google.com/macros/s/<ID>/exec
trip=20261118-210247.csv&off=0&total=312004&crc=9a3f1c22   (body)
<bytes do trecho, crus>
```

- A placa lê o arquivo do cartão em blocos de 8 KB e envia um bloco por vez.
- O script responde `{"ok":true,"off":<próximo byte>}`; o offset fica na NVS.
- Se cair, a próxima partida retoma do offset devolvido — nunca recomeça do zero.
- Limite por tentativa: 10 s de timeout, 1 tentativa por arquivo por boot.
- Sem resposta `ok`, **nada é apagado** e o arquivo continua na fila.

Por que blocos: o ESP32 tem ~300 KB de RAM livre e uma viagem de 1 h dá ~300 KB
de CSV. O arquivo não cabe inteiro na memória — tem de ir em pedaços.

## 4. Destino: Drive sem servidor

O caminho mais leve não é a API do Drive (exige OAuth e refresh token no
firmware). É um **Apps Script publicado como web app**, rodando na conta do dono:

- recebe o bloco por POST;
- acrescenta no arquivo da pasta `padaria/doblo/viagens`;
- responde o offset confirmado.

Vantagens: uma requisição HTTPS só, sem token no carro, sem servidor, sem custo.
A URL do script é o segredo (quem tem a URL pode postar) — aceitável para log de
carro, e dá para exigir um campo `token` fixo.

Alternativa sem Apps Script: a placa lista os arquivos na página e você baixa
quando quiser. Continua valendo como plano B quando não houver WiFi.

## 5. O que a placa guarda

| Dado | Onde | Tamanho aprox. | Política |
|---|---|---|---|
| Amostras crus da viagem | CSV no SD | ~300 KB por viagem | nunca apaga |
| Eventos detectados | JSONL no SD | < 5 KB por viagem | nunca apaga |
| DTC + freeze frame do início/fim | JSON no SD | ~1 KB por viagem | nunca apaga |
| Baselines e priors do bayes | NVS + arquivo | < 4 KB | reescrito pelo "estudo" |
| Redes e limiares (config) | NVS | < 2 KB | reescrito pela página |
| Fila de sincronização | NVS | < 1 KB | atualizada a cada envio |

Sem cartão, a flash interna (~3 MB) cobre ~80 h de direção se o log for binário
compacto, ou ~9 h em CSV. **Por isso o cartão é a opção mais simples**, não a
mais cara: evita buffer circular, desgaste de flash e perda da viagem que não
tem cópia em lugar nenhum.

## 6. Política de espaço

- Aviso na página e bipe quando o cartão passar de 80%.
- Em 100%: **para de gravar e bipa** — nunca apaga dado não sincronizado para
  abrir espaço.
- Arquivo já sincronizado só é apagado por ação explícita (botão), nunca
  automático.

## 7. Estrutura no cartão

```
/viagens/20261118-210247.csv      amostras
/viagens/20261118-210247.evt.jsonl  eventos
/viagens/20261118-210247.dtc.json   códigos + freeze frame
/config.json                      redes, limiares
/baseline.json                    medianas e priors
```

O CSV é o mesmo formato do `obd_doblo.py`, para o analisador de casa reaproveitar
os decodificadores que já existem.

## 8. Riscos conhecidos

- **Janela curta no boot**: se o DHCP do roteador for lento, 30 s podem não bastar
  na primeira tentativa — por isso a retomada é obrigatória, não opcional.
- **WiFi + Bluetooth no mesmo rádio**: enviar antes de abrir o SPP.
- **Hotspot do celular** gasta dados móveis; em roaming, desligar essa opção.
- **Rede com portal cativo** (hotel, shopping) não serve — só rede com IP direto.
- **Relógio errado** desalinha nome de arquivo e ordenação; depende do DS3231.
- **Corte de energia** no cartão: gravar em lote e `flush` a cada ~5 s.

## 9. Critérios de aceitação

1. Carro na garagem, WiFi da casa no alcance: uma partida envia as pendentes em
   blocos, sem notebook ligado.
2. Sem internet naquele boot: nada é apagado e a próxima partida tenta de novo.
3. Rede cai no meio: a próxima partida continua do offset devolvido pelo script.
4. Nenhuma rede conhecida: a placa sobe o AP e grava normalmente.
5. Cartão cheio: para de gravar, bipa, e mantém tudo o que tem.
6. Nenhuma credencial de nuvem dentro do firmware (só a URL do web app).

## 10. Em aberto

- CSV ou binário compacto na gravação (CSV é legível e reaproveita o analisador;
  binário quintuplica a autonomia sem cartão e cabe inteiro na RAM).
- Tamanho do bloco de upload (8 KB é o ponto de partida).
- Nome do AP e se o hotspot do celular entra na lista padrão.
- Se o "estudo" roda na placa ou só no celular/notebook depois do sync.
