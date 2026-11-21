# Estado do projeto — 21/11/2026

Retrato do que existe, do que foi medido e do que falta. Para não reconstruir
contexto a cada sessão.

## Funciona (testado)

- **ESP32 → dongle** por Bluetooth clássico (PIN `1234`), KWP fast na K-line.
- **Coleta binária**: 20 bytes por amostra, ~1,2 s por ciclo, ~60 KB/h, ~26 h na
  partição de 1,6 MB.
- **Página no celular**: temperatura, rotação, MAP, mistura, faixa de alerta.
- **Portal cativo**: entra na rede → o painel abre sozinho (iOS e Android).
- **AP fixo**: canal 1, só AP (sem estação), 4 clientes. IP em ~2 s.
- **Data sem RTC**: a página manda a hora do celular; a placa grava `# hora`.
- **DTC** cru do modo 03 em `.dtc` (P1220 gravado na central).
- **Upload para o Drive**: página → base64 → Apps Script → `Drive/doblo/viagens`.
- **Resgate por serial**: comando `x<NNNNN> csv` despeja o arquivo cru.

## Resgatado

35 viagens (`v00010`…`v00044`, ~396 KB) do firmware antigo, agora em
`C:\padaria\doblo\viagens`. Vieram pela serial, não pela rede — ver "o que morde".

## Não existe

- **Cartão SD** (tudo na flash interna).
- **Buzzer** (alarme é a faixa da página).
- **RTC** (hora depende do celular abrir a página).
- **GPS**: só via Atalho do iPhone (`?lat=&lon=`), nunca pelo navegador (HTTP).
- **Analisador offline** (features, baseline, anomalias) — próximo passo.
- **Instalação definitiva** no carro.

## Como testar no carro

1. Placa na tomada 12 V (USB), dongle no plugue, chave ligada.
2. Esperar ~20 s: a serial mostra `[1/6] … [6/6] pronto`.
3. Celular na rede `DobloOBD` → o portal abre o painel.
4. Ao sair, o painel mostra as pendentes e envia sozinho.

Se a tomada 12 V continuar energizada com a chave desligada, **tirar o cabo** —
~50 mA matam a bateria em semanas.

## O que morde

- **Abrir a serial (COM10) reseta a placa** (auto-reset do devkit).
- **AP+STA quebra o AP**: o ESP32 força o AP a seguir o canal da estação. Por isso
  não há mais estação; quem envia é o celular.
- **Bluetooth e WiFi dividem o rádio**: enquanto alguém usa o painel, o BT espera.
- **Rede instável derruba download em lote**: 35 arquivos por HTTP falharam; pela
  serial passaram. Em emergência, usar `x`.
- `o2a = 1,27 V` é "sonda fria/inválida", não mistura rica.
- Trims e avanço são **byte cru** de propósito: a escala padrão não vale aqui.
- O WiFi de casa não chega no porta-luvas (~-70 dBm pela lataria).

## Próximos passos

1. **Analisador offline** em Python: `analise/bin2csv.py` já converte; falta
   features, baseline e a saída de hipóteses.
2. Regras de diagnóstico (`regras.json` + avaliador) — as ~50 da conversa.
3. Testar o conjunto numa viagem real com o dongle em movimento.
