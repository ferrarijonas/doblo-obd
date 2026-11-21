# Regras de diagnóstico — o que cruzar e o que concluir

Primeira versão. Cada regra é uma **combinação de sinais**, não um limite
isolado. Confiança é julgamento, não validação estatística — com um carro só,
cada uma precisa ser confirmada na prática.

## Sinais que temos

10 vivos: RPM, velocidade, temp. motor, temp. ar, MAP, acelerador, carga, sonda 1,
sonda 2, status do combustível.
4 de estado: MIL, DTC, distância com MIL, freeze frame.
3 inúteis nesta central: STFT, LTFT, avanço (byte cru, escala inválida).

## Derivados que valem

| Info | Como | Revela |
|---|---|---|
| Consumo L/100 km | speed-density: MAP × RPM × cilindrada ÷ (R × T) ÷ AFR (E27 ≈ 13,4; etanol ≈ 9,0) | mistura rica, injetor, freio arrastando |
| Vácuo na lenta | baro − MAP | entrada falsa de ar |
| Altitude | MAP com motor parado = pressão atmosférica | normaliza tudo na serra |
| Tempo de partida | key-on até RPM > 400 | bateria, arranque |
| Estabilidade da lenta | desvio de RPM **e** de MAP a quente | borboleta, combustão |
| Aquecimento | tempo até 90 °C e o degrau do termostato | termostato |
| Banda da ventoinha | ciclos subir/cair parado | ventoinha, radiador |
| Razão RPM/velocidade | em marcha fixa | embreagem patinando |
| DFCO | acelerador fechado + MAP baixo + RPM alto | corte de injeção |
| Atividade da sonda | transições/min | sonda preguiçosa |

## Regras

| # | Combinação | Hipótese | Confiança |
|---|---|---|---|
| 1 | código de catalisador/sonda + temp acima do baseline + consumo ↑ + sonda 1 lenta | coolant no escape (junta) | alta |
| 2 | temp sobe com o carro andando (> 80 km/h) | radiador / fluxo | alta |
| 3 | temp sobe só parado e cai ao andar | ventoinha / relé | alta |
| 4 | aquecimento muito lento, temp cai em descida | termostato aberto | alta |
| 5 | vácuo na lenta baixo + MAP alto + RPM alto | entrada falsa de ar | média |
| 6 | MAP no WOT < 90% da baro | restrição (filtro, escape, catalisador) | média |
| 7 | sonda 1 < 0,3 V sob carga | falta de combustível (bomba/filtro/bico) | média |
| 8 | sonda 2 espelhando a sonda 1 | catalisador morto | alta |
| 9 | sonda 1 sem comutar por > 30 s em malha fechada | sonda preguiçosa/morta | alta |
| 10 | tempo de partida 2× o baseline + queda de tensão | bateria | alta |
| 11 | tensão < 13,2 V rodando, caindo com farol/AC | alternador | alta |
| 12 | RPM/velocidade fora da constante em marcha fixa | embreagem | média |
| 13 | σ RPM e σ MAP na lenta crescendo + P1220 recorrente | borboleta/pedal | alta |
| 14 | carga 20% acima do baseline na mesma velocidade | freio arrastando / pneu | baixa |

## O que não dá para ver

Pressão/temperatura de óleo, contador de misfire, bomba, bobina, câmbio, ABS,
airbag, VIN, odômetro, consumo real por sensor. A K-line a 1 Hz também não vê
evento rápido (misfire, dip de tensão).

## Onde as regras rodam

- **Ao vivo (placa):** só limite físico e forma (2, 3, 7, 9, 11).
- **Offline (Python):** todas, com baseline e histórico.

## Formato de saída

Nunca "seu carro quebrou". Sempre hipótese + base + o que conferir:

```
21/03 14:32 · viagem 118
HIPÓTESE: coolant no escape (junta) — confiança alta
  base: P0420 + temp 6 °C acima do baseline + consumo +22%
  conferir: nível do reservatório, teste de gases, sonda 1
```

## Backlog de detecção (não implementado)

- agrupar viagens por impressão digital de velocidade (rota sem GPS)
- CUSUM em tempo de partida, aquecimento e variância da lenta
- prior por contexto: viagem longa sobe arrefecimento/junta, curta sobe partida
