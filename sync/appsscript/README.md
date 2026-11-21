# Receptor no Drive (Apps Script)

Sem servidor, sem notebook, sem credencial no ESP32.

## Publicar (uma vez)

1. script.google.com → **Novo projeto** → cole `Code.gs`.
2. Troque `TROQUE_ESTE_TOKEN` por algo longo e aleatório.
3. **Implantar → Nova implantação → Tipo: App da Web**
   - Executar como: **eu**
   - Quem tem acesso: **qualquer pessoa**
4. Copie a URL `.../exec`. Ela é o endereço que vai no firmware.

## Testar sem ESP32

```bash
curl -X POST "URL/exec?token=SEGREDO&trip=20261118-210247.csv&off=0&total=26" \
     --data-binary "hora,RPM
00:00,800
"
```

Resposta esperada: `{"ok":true,"off":26,...}`.
Quando a soma dos blocos alcançar `total`, o arquivo aparece em
`Drive/doblo/viagens/` e a pasta temporária é descartada.

## Pegadinhas

- **302**: o Apps Script responde com redirect para `script.googleusercontent.com`.
  No ESP32, `HTTPClient` precisa seguir redirect em POST
  (`setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS)`).
- **TLS**: `WiFiClientSecure` com `setInsecure()` é o caminho curto; com
  `setCACert()` é o correto. Para começar, `setInsecure()`.
- **Tamanho do bloco**: 8 KB. Abaixo disso o overhead por requisição domina;
  acima, RAM e timeout apertam.
- **Ordem**: os blocos são nomeados pelo offset, então chegar fora de ordem não
  quebra nada.
- **Nunca apaga antes de `ok`**: o ESP32 só marca como sincronizado com a
  resposta positiva e o `off` devolvido.
- **Cota**: Apps Script aguenta folgado ~10 MB/mês, e cada execução tem 6 min.
