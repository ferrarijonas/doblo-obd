# Monitor OBD-II — Fiat Doblò 2016 Adventure 1.8 Flex

Lê o carro com um ELM327 Bluetooth e serve um painel no navegador do notebook:
valores ao vivo, gráfico de 60 amostras por sensor, log CSV de cada sessão,
leitura/apagamento de códigos de falha, varredura de **todos** os PIDs que a
central responde e uma aba de diagnóstico com protocolo e sensores suportados.

O que já foi descoberto sobre este carro (protocolo, PIDs, P1220, pegadinhas do
adaptador) está em **[DOCUMENTACAO.md](DOCUMENTACAO.md)**.

## Antes de rodar

1. Ligue a ignição (posição ON). Não precisa dar partida.
2. Pareie o ELM327 no Windows: Configurações → Bluetooth → adicionar dispositivo
   (`OBDII`, `V-LINK`, `ELM327`...). A senha é `1234` ou `0000`.
   Isso cria uma porta `COMx` — veja com `python obd_doblo.py --list`.
3. O plugue OBD do Doblò fica à esquerda da coluna de direção, na caixa de
   fusíveis (tampa plástica). Ligue o adaptador ali.

## Rodar

```bat
python obd_doblo.py --demo          :: primeiro teste, sem carro
python obd_doblo.py --port COM8     :: no carro (este Doblò = COM8, 38400 baud)
```

Abre sozinho em http://127.0.0.1:8770

- `--list` mostra as portas COM.
- Sem `--port`, ele tenta a primeira porta com "Bluetooth" na descrição — nesta
  máquina isso pega o fone/impressora, então **use `--port COM8`**.
- `--selftest` roda as checagens dos decodificadores (não precisa de carro).
- `--no-browser` não abre o navegador.

Só depende de `pyserial` (já instalado nesta máquina).

## O que esperar do carro

O Doblò 2016 vende no Brasil com OBD Br-2 (obrigatório desde 2011), então os PIDs
padrão de motor/emissões respondem: RPM, velocidade, temperatura do motor e do ar,
carga, acelerador, MAP, MAF, nível de combustível, trims, avanço.

**Medido neste carro (18/11/2026):** protocolo **KWP 2000 fast (ISO 14230-4), na
K-line** — não é CAN. O app fixa `ATSP5` e cai para auto se não responder. A
resposta de PIDs foi `4100BE3EB811`: 01, 03, 04, 05, 06, 07, 0B, 0C, 0D, 0E, 0F,
11, 13, 14, 15, 1C, 20. **MAF (0x10) não existe** nessa central, por isso esse
card não aparece no painel.

O que **não** sai pelo ELM327 genérico: ABS, airbag, câmbio, body computer e
controle de clima — isso é diagnóstico proprietário (AlfaOBD, MultiEcuScan).
PIDs marcados como "não suportados" na aba Diagnóstico simplesmente não existem
nessa central e são ignorados.

## Logs

`logs/viagem-AAAAMMDD-HHMMSS.csv`, uma linha a cada ciclo (~0,5 s), colunas com o
mesmo nome do painel. Abre direto no Excel (UTF-8 com BOM).

## Cuidados

- Apagar códigos (`apagar falhas`) zera os monitores de prontidão do OBD e o
  freeze frame. Anote os códigos antes; se for inspeção veicular, rode o carro
  alguns dias depois de apagar.
- Deixar o adaptador plugado com o carro desligado consome bateria devagar.
  O Doblò desliga a tomada OBD junto com a ignição, mas não conte com isso.
- Painel mostra dado de motor, não substitui instrumento do carro. Não fique
  mexendo no notebook dirigindo.

## Projetos que serviram de referência

- `Paul-HenryP/PyOBD-Dashboard` — painel Python + ELM327, log CSV, detecção de
  anomalias, dyno virtual.
- `provrb/obdium` — ferramenta Rust offline para ELM327, dados ao vivo e VIN.
- `fr3ts0n/AndrOBD` — app Android open source, referência de UI e de PIDs.
- `Ircama/ELM327-emulator` — simulador de ELM327 para testar sem carro.
- `AlveeeRahman/OpenCarMind` — ESP32-S3 + BLE + TinyML, para quem quiser tirar o
  notebook da jogada depois.
