"""Resgate dos logs pela serial USB e envio para o Apps Script.

Usar quando a rede da placa estiver instável: a serial não depende de rádio.
Lê a URL e o token de firmware/wifi_secrets.h (que não vai para o git).

    python resgate_serial.py            # resgata v00010..v00044 e envia
    python resgate_serial.py 10 20      # faixa de números
"""

import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import serial

RAIZ = Path(__file__).resolve().parent.parent
SEGREDOS = RAIZ / "firmware" / "wifi_secrets.h"
PORTA = os.environ.get("DOBLO_PORTA", "COM10")
SAIDA = RAIZ / "logs" / "resgatados"


def credenciais():
    txt = SEGREDOS.read_text(encoding="utf-8")
    url = re.search(r'SYNC_URL\s+"([^"]*)"', txt).group(1)
    tok = re.search(r'SYNC_TOKEN\s+"([^"]*)"', txt).group(1)
    if not url or not tok:
        raise SystemExit("SYNC_URL/SYNC_TOKEN vazios em firmware/wifi_secrets.h")
    return url, tok


def ler_ate(s, marca, limite):
    buf = b""
    t0 = time.time()
    while time.time() - t0 < limite:
        d = s.read(4096)
        if d:
            buf += d
            if marca in buf:
                return buf
        else:
            time.sleep(0.02)
    return buf


def dump(s, n):
    s.reset_input_buffer()
    s.write(("x%05d csv\n" % n).encode())
    cab = ler_ate(s, b"===\n", 8.0)
    linhas = [l for l in cab.split(b"\n") if l.startswith(b"===FILE")]
    if not linhas:
        return None, None
    partes = linhas[-1].decode().replace("===FILE", "").replace("===", "").split()
    if len(partes) < 2:
        return None, None
    nome, tam = partes[0], int(partes[1])
    corpo = cab.split(linhas[-1], 1)[1]
    t0 = time.time()
    while len(corpo) < tam and time.time() - t0 < 20:
        d = s.read(min(4096, tam - len(corpo)))
        if d:
            corpo += d
    ler_ate(s, b"===END===", 3.0)
    return os.path.basename(nome), corpo[:tam]


def main():
    ini = int(sys.argv[1]) if len(sys.argv) > 2 else 10
    fim = int(sys.argv[2]) if len(sys.argv) > 2 else 44
    url, tok = credenciais()
    SAIDA.mkdir(parents=True, exist_ok=True)

    s = serial.Serial(PORTA, 115200, timeout=0.3)
    print("boot (~20 s)...", flush=True)
    time.sleep(30)
    s.reset_input_buffer()

    salvos = []
    for n in range(ini, fim + 1):
        nome, corpo = dump(s, n)
        if nome and corpo and len(corpo) > 40:
            (SAIDA / nome).write_bytes(corpo)
            salvos.append((nome, corpo))
            print("ok %s %d" % (nome, len(corpo)), flush=True)
    s.close()
    print("resgatados:", len(salvos), flush=True)

    enviados = 0
    for nome, corpo in salvos:
        q = urllib.parse.urlencode({"token": tok, "trip": nome, "off": "0", "total": str(len(corpo))})
        req = urllib.request.Request(url + "?" + q, data=corpo, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                if '"ok":true' in r.read().decode():
                    enviados += 1
        except Exception as e:
            print("erro", nome, type(e).__name__, flush=True)
    print("enviados:", enviados, "de", len(salvos))


if __name__ == "__main__":
    main()
