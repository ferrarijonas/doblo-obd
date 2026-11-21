#!/usr/bin/env python3
"""Monitor OBD-II para Fiat Doblo 2016 Adventure 1.8 Flex (ELM327 Bluetooth).

  python obd_doblo.py --list          # ver portas COM
  python obd_doblo.py --demo          # painel sem carro, para testar
  python obd_doblo.py --port COM5     # no carro, ignicao ligada

Depois abra http://127.0.0.1:8770
"""
import argparse
import csv
import json
import math
import re
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import serial
from serial.tools import list_ports

HTTP_PORT = 8770
LOG_DIR = Path(__file__).with_name("logs")

# nome, PID (modo 01), bytes de dados, decodificador, unidade, prioridade
SENSORS = [
    ("RPM",         "010C", 2, lambda d: (d[0] * 256 + d[1]) / 4,      "rpm",  True),
    ("Velocidade",  "010D", 1, lambda d: d[0],                         "km/h", True),
    ("Acelerador",  "0111", 1, lambda d: d[0] * 100 / 255,             "%",    True),
    ("Carga",       "0104", 1, lambda d: d[0] * 100 / 255,             "%",    True),
    ("Temp. motor", "0105", 1, lambda d: d[0] - 40,                    "C",    False),
    ("Temp. ar",    "010F", 1, lambda d: d[0] - 40,                    "C",    False),
    ("MAP",         "010B", 1, lambda d: d[0],                         "kPa",  False),
    ("MAF",         "0110", 2, lambda d: (d[0] * 256 + d[1]) / 100,    "g/s",  False),
    ("Combustivel", "012F", 1, lambda d: d[0] * 100 / 255,             "%",    False),
    ("STFT*",       "0106", 1, lambda d: d[0] / 1.28 - 100,            "%",    False),
    ("LTFT*",       "0107", 1, lambda d: d[0] / 1.28 - 100,            "%",    False),
    ("Avanco",      "010E", 1, lambda d: d[0] / 2 - 64,                "grau", False),
    ("Consumo",     "015E", 2, lambda d: (d[0] * 256 + d[1]) / 20,     "L/h",  False),
]

PROTOCOLS = {"1": "J1850 PWM", "2": "J1850 VPW", "3": "ISO 9141-2",
             "4": "KWP 5 baud", "5": "KWP fast", "6": "CAN 11/500",
             "7": "CAN 29/500", "8": "CAN 11/250", "9": "CAN 29/250"}

# nome legivel de cada PID padrao, para a tabela "todos os PIDs"
PID_INFO = {int(s[1][2:], 16): (s[0], s[3], s[4]) for s in SENSORS}
PID_INFO.update({
    0x01: ("MIL / nº de falhas", None, ""),
    0x03: ("Status do sistema de combustível", None, ""),
    0x13: ("Sondas lambda presentes", None, ""),
    0x14: ("Sonda lambda 1 (V)", lambda d: d[0] / 200, "V"),
    0x15: ("Sonda lambda 2 (V)", lambda d: d[0] / 200, "V"),
    0x1C: ("Padrão OBD", None, ""),
    0x20: ("PIDs 21-40 suportados", None, ""),
    0x21: ("Distância com MIL aceso", lambda d: d[0] * 256 + d[1], "km"),
})

LOCK = threading.Lock()


def decode_dtc(b1, b2):
    return f"{'PCBU'[b1 >> 6]}{(b1 >> 4) & 3}{b1 & 0xF}{b2 >> 4}{b2 & 0xF}"


class Elm:
    """Conversa com o ELM327. Respostas de dados vem sem espacos: '410C1AF8'."""

    def __init__(self, port, baud=38400):
        self.ser = serial.Serial(port, baud, timeout=2.5, write_timeout=2.5)
        self.ser.write(b"\r")
        self.version = "?"
        self.protocol = "?"

    def cmd(self, c, timeout=3.0):
        self.ser.timeout = timeout
        self.ser.reset_input_buffer()
        self.ser.write((c + "\r").encode())
        raw = self.ser.read_until(b">").decode("ascii", "ignore")
        lines = []
        for line in raw.replace(">", "").splitlines():
            line = line.strip()
            if not line or line.upper() == "OK" or line.upper() == c.upper():
                continue
            if line.upper().startswith("SEARCHING"):
                continue
            lines.append(line)
        return lines

    def init(self):
        self.cmd("ATZ", timeout=4)
        time.sleep(0.4)
        for c in ("ATE0", "ATL0", "ATS0"):
            self.cmd(c)
        v = self.cmd("ATI")
        self.version = v[0] if v else "?"
        # Doblò 2016 responde KWP fast na K-line: fixar SP5 evita ~5s de
        # auto-busca a cada reconexao; se nao responder, volta para auto.
        usado = ""
        for sp in ("ATSP5", "ATSP0"):
            self.cmd(sp, timeout=4)
            if "4100" in "".join(self.cmd("0100", timeout=12)):
                usado = sp
                break
        d = self.cmd("ATDPN")
        if d:
            self.protocol = PROTOCOLS.get(d[0][-1], d[0])
        else:
            self.protocol = "KWP fast" if usado == "ATSP5" else "?"

    def pid(self, pid):
        for line in self.cmd(pid):
            h = re.sub(r"[^0-9A-F]", "", line.upper())
            if h.startswith("41" + pid[2:4]) and len(h) > 4:
                if len(h) % 2:
                    h += "0"
                return bytes.fromhex(h[4:])
        return None

    def voltage(self):
        for line in self.cmd("ATRV"):
            m = re.search(r"(\d+\.?\d*)", line)
            if m:
                return float(m.group(1))
        return None

    def vin(self):
        lines = self.cmd("0902", timeout=8)
        # KWP: resposta em registros "4902 0<linha> <4 bytes>"; junta e limpa NULs
        buf = b""
        for line in lines:
            h = re.sub(r"[^0-9A-F]", "", line.upper())
            m = re.search(r"49020[0-9]", h)
            if m:
                payload = h[m.end():]
                if len(payload) % 2:
                    payload = payload[:-1]
                buf += bytes.fromhex(payload)
        if buf:
            txt = buf.decode("ascii", "ignore").lstrip("\x00")
            v = re.search(r"[A-HJ-NPR-Z0-9]{17}", txt)
            if v:
                return v.group(0)
        # fallback: 17 caracteres direto no texto cru (estilo CAN multiframe)
        v = re.search(r"[A-HJ-NPR-Z0-9]{17}", "".join(lines))
        return v.group(0) if v else ""

    def mil(self):
        d = self.pid("0101")
        if not d:
            return None, None
        return bool(d[0] & 0x80), d[0] & 0x7F

    def dtcs(self):
        out = []
        for line in self.cmd("03", timeout=6):
            h = re.sub(r"[^0-9A-F]", "", line.upper())
            if not h.startswith("43"):
                continue
            body = h[2:]
            for i in range(0, len(body) - 3, 4):
                b1, b2 = int(body[i:i + 2], 16), int(body[i + 2:i + 4], 16)
                if b1 or b2:
                    out.append(decode_dtc(b1, b2))
        return out

    def clear(self):
        self.cmd("04")

    def supported(self):
        pids = set()
        for base in (0x00, 0x20, 0x40, 0x60):
            d = self.pid(f"01{base:02X}")
            if not d or len(d) < 4:
                continue
            bits = int.from_bytes(d[:4], "big")
            for i in range(32):
                if bits & (1 << (31 - i)):
                    pids.add(base + 1 + i)
        return pids

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class App:
    def __init__(self, args):
        self.args = args
        self.state = {
            "connected": False, "port": "", "protocol": "", "version": "", "vin": "",
            "voltage": None, "values": {}, "units": {s[0]: s[4] for s in SENSORS},
            "supported": [], "mil": None, "dtc_count": None, "dtcs": [],
            "logging": False, "logfile": "", "error": None, "cycles": 0, "demo": args.demo,
        }
        self.elm = None
        self.log = None
        self.writer = None
        self.stop = False

    # ---- conexao -------------------------------------------------------
    def connect(self):
        port = self.args.port or autodetect()
        if not port:
            self.state["error"] = "nenhuma porta serial encontrada; use --port COMx (--list mostra)"
            return False
        elm = None
        try:
            elm = Elm(port)
            elm.init()
            pids = elm.supported()
            supported = [s for s in SENSORS if int(s[1][2:], 16) in pids]
            if not supported:  # carro pode estar com ignicao desligada
                raise RuntimeError("adaptador respondeu, mas o carro nao. Ligue a ignicao.")
        except Exception as e:
            if elm:
                elm.close()
            self.state["error"] = f"falha em {port}: {e}"
            return False

        self.elm = elm
        self.state.update(connected=True, port=port, protocol=elm.protocol,
                          version=elm.version, vin=elm.vin(),
                          supported=[s[0] for s in supported], error=None)
        mil, count = elm.mil()
        self.state.update(mil=mil, dtc_count=count)
        self.start_log()
        print(f"conectado em {port} | {elm.version} | {elm.protocol} | VIN {self.state['vin'] or '-'}")
        print("PIDs suportados:", ", ".join(self.state["supported"]))
        return True

    # ---- log -----------------------------------------------------------
    def start_log(self):
        LOG_DIR.mkdir(exist_ok=True)
        path = LOG_DIR / f"viagem-{datetime.now():%Y%m%d-%H%M%S}.csv"
        self.log = open(path, "w", newline="", encoding="utf-8-sig")
        self.writer = csv.writer(self.log)
        self.writer.writerow(["hora"] + [s[0] for s in SENSORS])
        self.state.update(logging=True, logfile=str(path))
        print("gravando", path)

    def stop_log(self):
        if self.log:
            self.log.close()
        self.log = self.writer = None
        self.state.update(logging=False)

    def toggle_log(self):
        if self.state["logging"]:
            self.stop_log()
        else:
            self.start_log()

    def write_row(self):
        if not self.writer:
            return
        vals = self.state["values"]
        now = datetime.now()
        row = [now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"]
        for s in SENSORS:
            v = vals.get(s[0])
            row.append(f"{v:.2f}" if isinstance(v, (int, float)) else "")
        self.writer.writerow(row)
        self.log.flush()

    # ---- coleta --------------------------------------------------------
    def query_sensor(self, sensor):
        name, pid, n, parse, _unit, _fast = sensor
        d = self.elm.pid(pid)
        if d and len(d) >= n:
            try:
                self.state["values"][name] = round(float(parse(d)), 1)
            except Exception:
                pass

    def demo_cycle(self, t):
        k = t % 60
        v = {
            "RPM": 850 + 1800 * (0.5 + 0.5 * math.sin(k / 3)) + (60 if int(t * 3) % 7 else 0),
            "Velocidade": 40 + 40 * math.sin(k / 8),
            "Acelerador": 20 + 15 * math.sin(k / 3),
            "Carga": 25 + 20 * math.sin(k / 4),
            "Temp. motor": min(92, 60 + k),
            "Temp. ar": 27,
            "MAP": 35 + 20 * math.sin(k / 3),
            "MAF": 4 + 6 * math.sin(k / 3),
            "Combustivel": 62,
            "STFT": 1.5,
            "LTFT": -2.1,
            "Avanco": 12 + 8 * math.sin(k / 2),
            "Consumo": 7 + 3 * math.sin(k / 5),
        }
        self.state["values"] = {n: round(x, 1) for n, x in v.items()}
        self.state["voltage"] = 14.1
        self.state["protocol"] = "DEMO"
        self.state["version"] = "ELM327 demo"
        self.state["supported"] = [s[0] for s in SENSORS]
        self.state["connected"] = True
        self.state["port"] = "demo"

    def worker(self):
        t0 = time.time()
        slow_every = 5
        i = 0
        falhas = 0
        if self.args.demo:
            self.state.update(mil=False, dtc_count=0)
            self.start_log()
        while not self.stop:
            if self.args.demo:
                self.demo_cycle(time.time() - t0)
                self.write_row()
                self.state["cycles"] += 1
                time.sleep(0.3)
                continue

            if not self.elm:
                if not self.connect():
                    falhas += 1
                    # o Windows demora ate ~15s para liberar a COM do Bluetooth
                    time.sleep(min(15, 2 + falhas * 2))
                    continue
                falhas = 0

            supported = [s for s in SENSORS if s[0] in self.state["supported"]]
            try:
                with LOCK:
                    for s in supported:
                        if s[5]:
                            self.query_sensor(s)
                    if i % slow_every == 0:
                        for s in supported:
                            if not s[5]:
                                self.query_sensor(s)
                    self.state["voltage"] = self.elm.voltage()
            except Exception as e:
                self.state.update(connected=False, error=f"conexao caiu: {e}")
                self.elm.close()
                self.elm = None
                self.stop_log()
                falhas += 1
                time.sleep(4)   # porta BT precisa de tempo para soltar
                continue

            self.write_row()
            self.state["cycles"] += 1
            i += 1
            time.sleep(0.05)

    # ---- acoes do painel ------------------------------------------------
    def read_dtcs(self):
        if self.args.demo:
            return self.state["dtcs"]
        if not self.elm:
            return ["sem conexao"]
        with LOCK:
            codes = self.elm.dtcs()
            mil, count = self.elm.mil()
        self.state.update(dtcs=codes, mil=mil, dtc_count=count)
        return codes

    def clear_dtcs(self):
        if self.args.demo:
            self.state.update(dtcs=[], mil=False, dtc_count=0)
            return []
        if not self.elm:
            return ["sem conexao"]
        with LOCK:
            self.elm.clear()
            mil, count = self.elm.mil()
        self.state.update(dtcs=[], mil=mil, dtc_count=count)
        return []

    def scan_pids(self):
        """Le todo PID que o carro responde, como fazem os apps de scanner."""
        if self.args.demo or not self.elm:
            return []
        linhas = []
        with LOCK:
            pids = self.elm.supported()
            for pid in sorted(pids):
                d = self.elm.pid(f"01{pid:02X}")
                if not d:
                    continue
                nome, dec, un = PID_INFO.get(pid, (f"PID {pid:02X}", None, ""))
                val = ""
                if dec:
                    try:
                        val = round(float(dec(d)), 2)
                    except Exception:
                        val = ""
                linhas.append({"pid": f"0x{pid:02X}", "nome": nome,
                               "hex": d.hex().upper(), "valor": val, "un": un})
        return linhas


def autodetect():
    ports = list(list_ports.comports())
    for p in ports:
        if "bluetooth" in (p.description or "").lower():
            return p.device
    return ports[0].device if ports else None


PAGE = """<!doctype html>
<html lang=pt-BR><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Doblo - OBD</title>
<style>
:root{--bg:#0b0f14;--card:#121821;--line:#1e2731;--txt:#e6edf3;--dim:#7d8b9a;--ok:#3ddc84;--bad:#ff5252}
*{box-sizing:border-box}body{margin:0;font:14px/1.4 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--txt)}
header{display:flex;gap:12px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:2;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}
.pill{font-size:12px;padding:3px 9px;border-radius:99px;border:1px solid var(--line);color:var(--dim)}
.pill.on{color:var(--ok);border-color:#1f4030}.pill.off{color:var(--bad);border-color:#3a1f1f}
button{background:#1a232e;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
button:hover{background:#22303f}
#tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:10px;padding:14px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px 4px}
.tile .k{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim)}
.tile .v{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}
.tile .u{font-size:12px;color:var(--dim);margin-left:3px;font-weight:400}
canvas{display:block;width:100%;height:24px;margin-top:4px;opacity:.75}
section{padding:0 14px 22px}h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);margin:12px 0 8px}
pre{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;margin:0;font-size:12px;color:#c9d5e1;white-space:pre-wrap}
#dtcs{font-family:ui-monospace,Consolas,monospace;font-size:15px;line-height:1.7}
.bad{color:var(--bad)}.ok{color:var(--ok)}
</style>
<header>
  <h1>Doblo 2016 &middot; OBD</h1>
  <span id=conn class="pill">offline</span>
  <span id=proto class=pill>-</span>
  <span id=volt class=pill>-</span>
  <span id=rec class=pill>log parado</span>
  <button id=btnlog>log</button>
  <button id=btndtc>ler falhas</button>
  <button id=btnclr>apagar falhas</button>
  <button id=btnpids>todos os PIDs</button>
</header>
<div id=tiles></div>
<section>
  <h2>Codigos de falha</h2>
  <div id=dtcs style="color:var(--dim)">clique em "ler falhas"</div>
</section>
<section>
  <h2>Todos os PIDs (leitura crua)</h2>
  <pre id=allpids>clique em "todos os PIDs"</pre>
</section>
<section>
  <h2>Diagnostico</h2>
  <pre id=diag>-</pre>
</section>
<script>
const $ = s => document.querySelector(s);
const H = {};            // historico para o sparkline
const MAX = 60;
let built = false;

function tile(k, u) {
  const d = document.createElement('div');
  d.className = 'tile';
  d.innerHTML = `<div class=k>${k}</div><div class=v><span id="v-${k}">-</span><span class=u>${u}</span></div><canvas width=200 height=24></canvas>`;
  return d;
}
function spark(cv, arr) {
  const c = cv.getContext('2d'), w = cv.width, h = cv.height;
  c.clearRect(0, 0, w, h);
  if (arr.length < 2) return;
  const lo = Math.min(...arr), hi = Math.max(...arr), sp = hi - lo || 1;
  c.beginPath();
  arr.forEach((v, i) => {
    const x = i / (MAX - 1) * w, y = h - 2 - (v - lo) / sp * (h - 4);
    i ? c.lineTo(x, y) : c.moveTo(x, y);
  });
  c.strokeStyle = '#3ddc84'; c.lineWidth = 1.6; c.stroke();
}

async function tick() {
  try {
    const s = await (await fetch('/api/state')).json();
    $('#conn').textContent = s.connected ? 'conectado ' + s.port : (s.demo ? 'demo' : 'offline');
    $('#conn').className = 'pill ' + (s.connected ? 'on' : 'off');
    $('#proto').textContent = s.protocol || '-';
    $('#volt').textContent = s.voltage ? s.voltage.toFixed(1) + ' V' : '-';
    $('#rec').textContent = s.logging ? 'gravando' : 'log parado';
    $('#rec').className = 'pill ' + (s.logging ? 'on' : '');
    $('#btnlog').textContent = s.logging ? 'parar log' : 'gravar log';

    const names = Object.keys(s.values);
    if (!built && names.length) {
      $('#tiles').innerHTML = '';
      names.forEach(n => $('#tiles').appendChild(tile(n, s.units[n] || '')));
      built = true;
    }
    names.forEach(n => {
      const el = document.getElementById('v-' + n);
      if (!el) return;
      el.textContent = s.values[n].toFixed(Math.abs(s.values[n]) < 10 ? 1 : 0);
      (H[n] = H[n] || []).push(s.values[n]);
      if (H[n].length > MAX) H[n].shift();
      spark(el.closest('.tile').querySelector('canvas'), H[n]);
    });

    if (s.dtcs && s.dtcs.length) {
      $('#dtcs').innerHTML = s.dtcs.map(c => `<span class=bad>${c}</span>`).join('<br>') +
        (s.mil ? '<br><span class=bad>MIL aceso</span>' : '');
    } else if (s.dtcs) {
      $('#dtcs').innerHTML = s.mil ? '<span class=bad>MIL aceso, nenhum codigo lido</span>'
                                   : '<span class=ok>nenhum codigo gravado</span>';
    }
    $('#diag').textContent = [
      'adaptador : ' + (s.version || '-'),
      'protocolo : ' + (s.protocol || '-'),
      'VIN       : ' + (s.vin || '-'),
      'porta     : ' + (s.port || '-'),
      'ciclos    : ' + s.cycles,
      'sensores  : ' + (s.supported.join(', ') || '-'),
      'MIL       : ' + (s.mil === null ? '-' : (s.mil ? 'aceso' : 'apagado')),
      'log       : ' + (s.logfile || '-'),
      s.error ? 'erro      : ' + s.error : ''
    ].join('\\n');
  } catch (e) { /* servidor fora do ar */ }
}

$('#btnlog').onclick = () => fetch('/api/log', { method: 'POST' });
$('#btndtc').onclick = async () => {
  $('#dtcs').textContent = 'lendo...';
  await fetch('/api/dtc/read', { method: 'POST' });
};
$('#btnclr').onclick = async () => {
  if (!confirm('Apagar os codigos de falha do carro?')) return;
  await fetch('/api/dtc/clear', { method: 'POST' });
};
$('#btnpids').onclick = async () => {
  $('#allpids').textContent = 'lendo todos os PIDs (leva ~10 s)...';
  try {
    const r = await fetch('/api/pids').then(r => r.json());
    $('#allpids').textContent = r.pids.map(p =>
      p.pid + '  ' + p.nome.padEnd(32, ' ') + String(p.valor).padStart(8) + ' ' +
      (p.un || '') + '   [' + p.hex + ']'
    ).join('\n') || 'nenhum PID respondido';
  } catch (e) { $('#allpids').textContent = 'erro ao ler'; }
};
setInterval(tick, 400); tick();
</script>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    app = None

    def _send(self, body, ctype="application/json", code=200):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(PAGE, "text/html")
        elif self.path == "/api/state":
            self._send(json.dumps(self.app.state))
        elif self.path == "/api/pids":
            self._send(json.dumps({"pids": self.app.scan_pids()}))
        else:
            self._send("{}", code=404)

    def do_POST(self):
        if self.path == "/api/log":
            self.app.toggle_log()
            self._send(json.dumps({"ok": True}))
        elif self.path == "/api/dtc/read":
            self._send(json.dumps({"dtcs": self.app.read_dtcs()}))
        elif self.path == "/api/dtc/clear":
            self._send(json.dumps({"dtcs": self.app.clear_dtcs()}))
        else:
            self._send("{}", code=404)

    def log_message(self, *a):
        pass


class FakeSerial:
    """ELM327 de mentira, para testar o parser sem carro."""

    def __init__(self, table):
        self.table = table
        self.out = b""
        self.timeout = 1

    def write(self, data):
        cmd = data.decode().strip()
        self.out = (self.table.get(cmd, "NO DATA") + "\r\r>").encode()

    def read_until(self, _term):
        return self.out

    def reset_input_buffer(self):
        pass


def selftest():
    assert decode_dtc(0x01, 0x33) == "P0133"
    assert decode_dtc(0x03, 0x00) == "P0300"
    assert decode_dtc(0xC1, 0x23) == "U0123"
    rpm = SENSORS[0][3](bytes([0x1A, 0xF8]))
    assert rpm == 1726.0, rpm
    assert SENSORS[1][3](bytes([0x64])) == 100
    assert SENSORS[4][3](bytes([0x7B])) == 83          # 123-40
    assert SENSORS[9][3](bytes([0x80])) == 0.0         # trim neutro
    assert SENSORS[11][3](bytes([0x80])) == 0.0        # avanco zero
    assert "<html" in PAGE and PAGE.rstrip().endswith("</script>\n</html>")

    fake = FakeSerial({
        "010C": "410C1AF8",
        "010D": "410D3C",
        "0100": "4100BE1FA813",
        "0120": "412000000001",
        "03": "4301330000",
        "0101": "410182",
        "0902": "49020131425A5A\r4902025A313241\r49020333585934\r49020435363738\r49020539000000",
        "ATRV": "12.6V",
        "ATDPN": "A6",
    })
    elm = Elm.__new__(Elm)
    elm.ser = fake
    assert elm.pid("010C") == b"\x1a\xf8"
    assert elm.pid("010D") == b"\x3c"
    assert elm.dtcs() == ["P0133"]
    assert elm.mil() == (True, 2)
    assert elm.voltage() == 12.6
    assert elm.vin() == "1BZZZ12A3XY456789", elm.vin()
    assert 0x0C in elm.supported() and 0x0D in elm.supported()
    # o filtro de sensores usa o PID sem o byte de modo (0x0C, nao 0x010C)
    pids = {0x0C, 0x0D, 0x05}
    nomes = [s[0] for s in SENSORS if int(s[1][2:], 16) in pids]
    assert nomes == ["RPM", "Velocidade", "Temp. motor"], nomes
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="porta serial do ELM327 (ex: COM5)")
    ap.add_argument("--http-port", type=int, default=HTTP_PORT)
    ap.add_argument("--demo", action="store_true", help="dados falsos, sem carro")
    ap.add_argument("--list", action="store_true", help="listar portas seriais")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print(f"{p.device:10} {p.description}")
        return
    if args.selftest:
        selftest()
        return

    app = App(args)
    Handler.app = app
    threading.Thread(target=app.worker, daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", args.http_port), Handler)
    url = f"http://127.0.0.1:{args.http_port}"
    print("painel em", url, "- Ctrl+C para sair")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop = True
        app.stop_log()
        if app.elm:
            app.elm.close()


if __name__ == "__main__":
    main()
