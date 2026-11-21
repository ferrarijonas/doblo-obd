# Firmware ESP32 — logger do Doblò

Placa: **ESP32-D0WD-V3 rev 3.1**, 4 MB, USB-UART CP2102 (COM10 no PC).
Arduino core esp32 **3.2.1** (o arduino-cli vem embutido no Arduino IDE 2.x).

## Compilar e gravar

```bat
"C:\Users\Alice\AppData\Local\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" ^
  compile --upload -p COM10 --fqbn esp32:esp32:esp32 ^
  --board-options PartitionScheme=custom "C:\jonas\carro\firmware\esp32_link"
```

O `partitions.csv` da pasta do sketch define o layout:

```
nvs        20 KB
otadata     8 KB
app0     1472 KB
spiffs   2496 KB   ← 2,5 MB próprios do projeto
coredump   64 KB
```

Conferido lendo a tabela de volta do chip (`esptool read-flash 0x8000 0xC00`).
O "16 MB" que a compilação imprime é só o valor de fachada da opção *Custom*.

## Achados do bring-up (18/11/2026)

- **Descobrir funciona**: `SerialBT.discover(12000)` lista os aparelhos.
  O dongle aparece como `OBDII` / `01:23:45:67:89:BA`.
- **RSSI importa**: -86 dBm (PC longe do carro) não conecta; -68 dBm (porta-luvas)
  já é faixa utilizável para Bluetooth clássico.
- **Pareamento**: o clone exige PIN `1234`. A API é
  `SerialBT.setPin("1234", 4)` — a versão de um argumento não existe no core 3.2.1.
- **`connect()` usa segurança por padrão**
  (`ESP_SPP_SEC_ENCRYPT | ESP_SPP_SEC_AUTHENTICATE`), ou seja, sem pareamento
  prévio a conexão falha mesmo com sinal bom. Alternativa a testar se o PIN não
  bastar: `connect(addr, 0, ESP_SPP_SEC_NONE)`.
- **Bug do core**: depois de `connect()` falhar repetidamente, o firmware pode dar
  *stack smashing* e reiniciar. Limitar a 2 tentativas por boot.
- **Anti-OTA**: a partição não tem segundo slot de app, então atualização é só por
  cabo. É intencional — o carro não fica em rede de casa durante a noite.

## Formato do CSV (contrato com o analisador)

Uma linha por ciclo (~770 ms), 17 colunas. `-1` = nunca lido ainda.

| coluna | PID | unidade | observação |
|---|---|---|---|
| `ms` | — | ms | desde o boot (sem RTC ainda) |
| `rpm` | 010C | rpm | |
| `vel` | 010D | km/h | |
| `tps` | 0111 | % | borboleta comandada, não o pedal |
| `carga` | 0104 | % | carga calculada |
| `temp` | 0105 | °C | |
| `ar` | 010F | °C | admissão |
| `map` | 010B | kPa | |
| `stft` | 0106 | **byte cru 0–255** | escala não confiável nesta central |
| `ltft` | 0107 | **byte cru 0–255** | idem |
| `avanc` | 010E | **byte cru 0–255** | idem |
| `o2a` | 0114 | V | sonda antes do catalisador |
| `o2b` | 0115 | V | depois do catalisador |
| `fuel` | 0103 | 1/2 | 1 = malha aberta, 2 = fechada |
| `mil` | 0101 | 0/1 | luz de injeção |
| `dtc` | 0101 | nº | códigos gravados |
| `falhas` | — | nº | leituras que falharam neste ciclo |

Os três bytes crus ficam assim de propósito: já descobrimos uma vez que a
decodificação padrão não vale para esta central, e byte cru é a única coisa que
permite redecidir depois. O lado de arquivo guarda o resto em unidade final.

Arquivos: `/v00001.csv`, `/v00002.csv`… (contador na NVS, sobrevive a reboot) e
`/v00001.dtc` com a resposta crua do modo 03 do início da viagem.

## Página no celular

A placa tenta entrar no `Alice` por 6 s; se não conseguir, cria o AP `DobloOBD`.
O IP aparece no boot pela serial (`wifi: <ip>` ou `AP ... ip <ip>`).

| rota | o que é |
|---|---|
| `/` | painel: temperatura, rotação, MAP, mistura + faixa de alerta |
| `/api` | JSON com todos os valores (é o que a página consome) |
| `/log` | baixa o CSV da viagem atual |

A página funciona sem internet: ela vive na flash da placa. No celular, "adicionar
à tela inicial" vira um ícone.

## Onde prender a placa

Porta-luvas (plástico), a ~40 cm do dongle. A caixa de fusíveis fica cercada de
chapa, que desintoniza a antena de PCB. Se o sinal cair, o caminho é módulo com
antena externa (u.FL), não mudar de lugar.
