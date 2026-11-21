"""Converte o log binário do ESP32 (DBL1, registros de 20 bytes) em CSV.

Uso:
    python bin2csv.py v00023.bin          # gera v00023.csv
    python bin2csv.py v00023.bin -o x.csv
"""

import struct
import sys
from pathlib import Path

CABECALHO = [
    "ms", "rpm", "vel", "tps", "carga", "temp", "ar", "map",
    "stft_raw", "ltft_raw", "avanc_raw", "o2a", "o2b", "fuel", "mil", "dtc", "falhas",
]


def registros(dados: bytes):
    if dados[:4] != b"DBL1":
        raise SystemExit("arquivo sem cabecalho DBL1")
    for i in range(4, len(dados) - 19, 20):
        yield dados[i:i + 20]


def decodifica(r: bytes):
    ms = struct.unpack_from("<I", r, 0)[0]
    rpm = struct.unpack_from("<H", r, 4)[0]
    v = [
        ms,
        "" if rpm == 0xFFFF else rpm / 4,
        "" if r[6] == 0xFF else r[6],
        "" if r[7] == 0xFF else r[7],
        "" if r[8] == 0xFF else r[8],
        "" if r[9] == 0xFF else r[9] - 40,
        "" if r[10] == 0xFF else r[10] - 40,
        "" if r[11] == 0xFF else r[11],
        "" if r[12] == 0xFF else r[12],
        "" if r[13] == 0xFF else r[13],
        "" if r[14] == 0xFF else r[14],
        "" if r[15] == 0xFF else round(r[15] / 200, 2),
        "" if r[16] == 0xFF else round(r[16] / 200, 2),
        "" if r[17] == 0xFF else r[17],
        (r[18] >> 7) & 1,
        r[18] & 0x7F,
        r[19],
    ]
    return v


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    origem = Path(sys.argv[1])
    destino = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "-o" else origem.with_suffix(".csv")

    dados = origem.read_bytes()
    linhas = [",".join(CABECALHO)]
    for r in registros(dados):
        linhas.append(",".join(str(x) for x in decodifica(r)))
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"{len(linhas) - 1} amostras -> {destino}")


if __name__ == "__main__":
    main()
