# Estado do projeto — 19/11/2026

O que já existe de verdade, o que falta, e como testar amanhã.

## Funciona

- **ESP32 → dongle** por Bluetooth clássico (PIN `1234`), KWP fast na K-line.
- **Coleta**: registros binários de 20 bytes, ~1,2 s por ciclo, ~60 KB/h, ~26 h de
  capacidade (partição de 1,6 MB após o app crescer).
- **Página no celular**: temperatura, rotação, MAP, mistura, faixa de alerta.
  `/api` (JSON) e `/log` (baixa o `.bin`).
- **Data sem RTC**: a página manda a hora do celular (`/hora?ts=`) e a placa
  grava a marca `# hora <epoch> <ms>` dentro do log.
- **Código de falha** cru do modo 03 salvo em `.dtc` (hoje: P1220).

## Não existe ainda

- **Upload para o Drive** — script pronto em `sync/appsscript/`, não publicado,
  e o firmware não envia.
- **Cartão SD** — tudo na flash interna (13 h).
- **Buzzer** — alarme é só a faixa da página.
- **RTC** — a hora depende do celular abrir a página.
- **Instalação no carro** — hoje é protótipo com o notebook.

## Como testar

1. Placa no carro, USB de celular na tomada 12 V, chave ligada.
2. Esperar ~30 s (boot + init da K-line).
3. Celular na rede `DobloOBD` (senha em `firmware/wifi_secrets.h`), abrir `http://192.168.4.1`.
4. `/log` baixa o `.bin`.

Se a tomada 12 V continuar energizada com a chave desligada, **tirar o cabo** —
o devkit consome ~50 mA e mata a bateria do carro em semanas.

## Detalhes que mordem

- Abrir a porta serial (COM10) **reseta a placa** — o devkit tem auto-reset.
- O `flush` da flash trava a gravação ~3 s a cada 20 linhas (não perde dado).
- `o2a = 1,27 V` é o marcador de "sonda fria/inválida", não mistura rica.
- Trims e avanço vêm em **byte cru** de propósito: a escala padrão não vale
  nesta central.
- O sinal do WiFi de casa **não chega** no porta-luvas (~-70 dBm pela lataria),
  então o AP próprio é o caminho normal dentro do carro.

## Próximos passos, em ordem

1. Publicar o Apps Script e implementar o envio (firmware + curl de teste).
2. Analisador offline em Python lendo o CSV (features, baseline, anomalias).
3. Ver a página funcionando de verdade numa viagem.
