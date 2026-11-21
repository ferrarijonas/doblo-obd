# Firmware ESP32 — logger do Doblò

Placa: **ESP32-D0WD-V3 rev 3.1**, 4 MB, USB-UART CP2102 (COM10 no PC).
Arduino core esp32 **3.2.1** (o `arduino-cli` vem embutido no Arduino IDE 2.x).

## Compilar e gravar

```bat
"C:\Users\Alice\AppData\Local\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" ^
  compile --upload -p COM10 --fqbn esp32:esp32:esp32 ^
  --board-options PartitionScheme=custom "C:\jonas\carro\firmware\esp32_logger"
```

O `partitions.csv` da pasta do sketch define o layout:

```
nvs        20 KB
otadata     8 KB
app0     2368 KB   (o WiFi + WebServer empurraram o firmware para 1,69 MB)
spiffs   1600 KB   → ~26 h de log binário
coredump   64 KB
```

O "16 MB" que a compilação imprime é só o valor de fachada da opção *Custom*.

## Achados do bring-up

- **Descobrir funciona**: `SerialBT.discover(12000)` lista os aparelhos. O dongle
  aparece como `OBDII` / `01:23:45:67:89:BA`.
- **RSSI importa**: -86 dBm não conecta; -65 dBm (porta-luvas) conecta de primeira.
- **Pareamento**: o clone exige PIN `1234` — `SerialBT.setPin("1234", 4)`
  (a versão de um argumento não existe no core 3.2.1).
- **`connect()` usa segurança por padrão** (`ESP_SPP_SEC_ENCRYPT |
  ESP_SPP_SEC_AUTHENTICATE`), então sem pareamento a conexão falha mesmo com
  sinal bom.
- **Bug do core**: depois de `connect()` falhar repetidamente o firmware pode dar
  *stack smashing*. Limitar a 2 tentativas por boot.
- **Boot em ~18 s** até a primeira amostra: `ATZ` + `BUS INIT` da K-line.
- **Abrir a porta serial reseta a placa** (auto-reset do devkit): cada leitura
  pelo PC começa um arquivo novo.
- **A partição sem OTA**: atualização é só por cabo. Intencional.

## Página no celular

O AP `DobloOBD` sobe **sempre**, antes do Bluetooth (~1 s). A estação de casa é
tentada em paralelo, sem bloquear. Foi a correção do sintoma "entro no carro e a
rede não aparece / na estrada aparece".

| rota | o que é |
|---|---|
| `/` | painel: temperatura, rotação, MAP, mistura + faixa de alerta |
| `/api` | JSON com todos os valores (inclui URL e token do sync) |
| `/log?f=` | baixa um arquivo (`.bin`) |
| `/pendentes` | lista o que falta enviar |
| `/marcar?f=` | grava o marcador `.ok` |
| `/geo?lat&lon&alt` | grava `# geo` no log (vem do Atalho do iPhone) |
| `/hora?ts=` | hora do celular |

A página envia sozinha o que estiver pendente ao abrir, por formulário escondido
(contorna o CORS do Apps Script), e mostra o contador.

## Formato do log (binário, 20 bytes por amostra)

Texto não cabia: o CSV dava **78,2 bytes/linha** = 6,6 h na partição. Binário fixo
dá **20 bytes** = ~26 h, sem custo de performance.

```
offset  campo      tipo    escala
0..3    ms         uint32  ms desde o boot
4..5    rpm        uint16  x4  (0xFFFF = inválido)
6       vel        uint8   km/h
7       tps        uint8   %
8       carga      uint8   %
9       temp       uint8   °C + 40
10      ar         uint8   °C + 40
11      map        uint8   kPa
12      stft       uint8   byte cru
13      ltft       uint8   byte cru
14      avanc      uint8   byte cru
15      o2a        uint8   V x 200
16      o2b        uint8   V x 200
17      fuel       uint8   1/2
18      mil|dtc    uint8   bit7 = MIL, 7 bits = contagem
19      falhas     uint8   leituras que falharam no ciclo
```

Cabeçalho de 4 bytes `DBL1`, depois registros fixos. `0xFF` = valor inválido.

Para ler: `python analise/bin2csv.py v00023.bin` — gera CSV com os mesmos nomes
de coluna de antes.

Os três bytes crus (stft, ltft, avanc) continuam crus de propósito: já
descobrimos uma vez que a decodificação padrão não vale para esta central.

Arquivos: `/v00001.bin`, `/v00002.bin`… (contador na NVS) e `/v00001.dtc` com a
resposta crua do modo 03.

## Estabilidade

| Recurso | Como |
|---|---|
| Task watchdog | 40 s, armado só depois do init (o boot passa de 20 s) |
| Motivo do reset | `esp_reset_reason()` no boot + contadores por tipo na NVS (`boots`, `r_panic`, `r_wdt`, `r_brownout`…) |
| Reconexão Bluetooth | callback de `ESP_SPP_CLOSE_EVT` + nova tentativa a cada 15 s, seguida de `reinitElm()` |
| Reconexão WiFi | `onEvent` + `reconnect()` a cada 30 s se o evento não vier; `persistent(false)` para não gastar flash |
| ECU dormindo | `3E 00` (TesterPresent) quando passa 3 s sem leitura bem-sucedida |
| Portal cativo | DNS responde tudo com o IP do AP e rota desconhecida devolve 302 para `/` — iOS e Android abrem o painel sozinhos |

O portal é o que resolve o "rede sem internet": o telefone mostra a folha de
"entrar na rede" já com o painel dentro. Não substitui o Atalho para GPS — a
localização continua bloqueada em `http://`.

## O que NÃO foi copiado dos projetos de referência

- **Auto-ajuste de PID** (dropar PID que falha 3x): no nosso caso a falha é a ECU
  dormindo, não PID inexistente — desativar seria permanente depois de um boot com
  a chave no acessório.
- **Scheduler por tela**: o painel é fixo; não há página escondida para priorizar.
- **Tela touch**: o celular é a tela.

## Onde prender a placa

Porta-luvas (plástico), a ~40 cm do dongle. A caixa de fusíveis fica cercada de
chapa, que desintoniza a antena de PCB. Se o sinal cair, o caminho é módulo com
antena externa (u.FL), não mudar de lugar.
