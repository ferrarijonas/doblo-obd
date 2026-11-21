// Doblò — logger + painel + envio para o Drive pelo celular.
//
// Serial: 'd' despeja o CSV atual, 's' status.
// Web:  /            painel (envia pendentes sozinho ao abrir)
//       /api         JSON
//       /log?f=arq   baixa um arquivo
//       /pendentes   lista o que falta enviar
//       /marcar?f=   marca como enviado
//       /geo?lat&lon&alt  grava a posição no CSV (vem do Atalho do iPhone)
//       /hora?ts=    hora do celular

#include <BluetoothSerial.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WebServer.h>
#include "../wifi_secrets.h"

BluetoothSerial BT;
Preferences prefs;
WebServer web(80);

static const char *MAC_DONGLE = "01:23:45:67:89:BA";
static const uint32_t CICLO_MS = 120;
static const int PINO_BUZ = 25;

unsigned long tUltimoCiclo = 0;
unsigned long ciclos = 0;
unsigned long semResposta = 0;
String arquivo;
File csv;
bool gravando = false;

float vRpm = -1, vVel = -1, vTps = -1, vCarga = -1, vTemp = -1, vAr = -1, vMap = -1;
float vStft = -1, vLtft = -1, vAvanc = -1, vO2a = -1, vO2b = -1, vFuel = -1;
int vMil = -1, vDtc = -1;
int falhasCiclo = 0;
int falhasSeguidas = 0;
long epochBase = 0;

// ---------------------------------------------------------------- ELM

String at(const char *c, uint32_t tmo = 2500) {
  while (BT.available()) BT.read();
  BT.write((const uint8_t *)c, strlen(c));
  BT.write('\r');
  String r;
  uint32_t t0 = millis();
  while (millis() - t0 < tmo) {
    if (BT.available()) {
      char ch = BT.read();
      if (ch == '>') break;
      if (ch != '\r') r += ch;
    }
    delay(1);
  }
  r.trim();
  return r;
}

String soHex(String s) {
  String h;
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s[i];
    if (isxdigit((unsigned char)c)) h += (char)toupper((unsigned char)c);
  }
  return h;
}

bool lerPid(const char *req, uint8_t *buf, uint8_t n, uint32_t tmo = 1200) {
  String h = soHex(at(req, tmo));
  String alvo = String("41") + String(req + 2);
  int p = h.indexOf(alvo);
  if (p < 0 || h.length() < (unsigned int)(p + 4 + n * 2)) return false;
  String d = h.substring(p + 4);
  for (uint8_t i = 0; i < n; i++)
    buf[i] = (uint8_t)strtol(d.substring(i * 2, i * 2 + 2).c_str(), NULL, 16);
  return true;
}

bool conectarDongle() {
  BT.begin("DobloOBD", true);
  delay(1500);
  BT.setPin("1234", 4);
  BTAddress alvo(MAC_DONGLE);
  for (int i = 0; i < 3; i++) {
    if (BT.connect(alvo)) return true;
    delay(1200);
  }
  return false;
}

void reinitElm() {
  Serial.println("reinit ELM");
  if (!BT.connected()) conectarDongle();
  at("ATZ", 4000);
  at("ATE0"); at("ATL0"); at("ATS0");
  at("ATSP5", 1500);
  uint8_t b[4];
  if (lerPid("0100", b, 4, 8000)) Serial.println("ELM recuperado");
  else Serial.println("ELM ainda sem resposta");
}

// ---------------------------------------------------------------- arquivo

void abrirCsv() {
  uint32_t boot = prefs.getUInt("boot", 0) + 1;
  prefs.putUInt("boot", boot);
  char nome[24];
  snprintf(nome, sizeof(nome), "/v%05u.bin", boot);
  arquivo = nome;
  csv = LittleFS.open(arquivo, FILE_WRITE);
  if (!csv) {
    Serial.println("FALHOU ao abrir CSV");
    return;
  }
  csv.write((const uint8_t *)"DBL1", 4);  // magic + versao
  csv.flush();
  gravando = true;
  Serial.printf("gravando em %s\n", arquivo.c_str());
}

void gravarDtc() {
  String r = at("03", 4000);
  String path = arquivo;
  path.replace(".bin", ".dtc");
  File f = LittleFS.open(path, FILE_WRITE);
  if (!f) return;
  f.println(r);
  f.close();
  Serial.printf("DTC cru: %s\n", r.c_str());
}

void gravarLinha() {
  if (!gravando || !csv) return;
  // Registro fixo de 20 bytes (documentado em firmware/README.md).
  // 0xFF = valor inválido.
  uint8_t b[20];
  uint32_t ms = millis();
  uint16_t rpm = (vRpm < 0) ? 0xFFFF : (uint16_t)(vRpm * 4);
  b[0] = ms & 0xFF; b[1] = (ms >> 8) & 0xFF; b[2] = (ms >> 16) & 0xFF; b[3] = (ms >> 24) & 0xFF;
  b[4] = rpm & 0xFF; b[5] = (rpm >> 8) & 0xFF;
  b[6] = vVel < 0 ? 0xFF : (uint8_t)min(255.0f, vVel);
  b[7] = vTps < 0 ? 0xFF : (uint8_t)min(100.0f, vTps);
  b[8] = vCarga < 0 ? 0xFF : (uint8_t)min(100.0f, vCarga);
  b[9] = vTemp < 0 ? 0xFF : (uint8_t)min(255.0f, vTemp + 40);
  b[10] = vAr < 0 ? 0xFF : (uint8_t)min(255.0f, vAr + 40);
  b[11] = vMap < 0 ? 0xFF : (uint8_t)min(255.0f, vMap);
  b[12] = vStft < 0 ? 0xFF : (uint8_t)vStft;   // byte cru
  b[13] = vLtft < 0 ? 0xFF : (uint8_t)vLtft;   // byte cru
  b[14] = vAvanc < 0 ? 0xFF : (uint8_t)vAvanc; // byte cru
  b[15] = vO2a < 0 ? 0xFF : (uint8_t)min(255.0f, vO2a * 200);
  b[16] = vO2b < 0 ? 0xFF : (uint8_t)min(255.0f, vO2b * 200);
  b[17] = vFuel < 0 ? 0xFF : (uint8_t)vFuel;
  b[18] = (uint8_t)((vMil > 0 ? 0x80 : 0) | (vDtc > 0 ? min(127, vDtc) : 0));
  b[19] = (uint8_t)min(255, falhasCiclo);
  csv.write(b, sizeof(b));
  if (ciclos % 20 == 0) csv.flush();
}

// ---------------------------------------------------------------- leitura

void lerRapidos() {
  uint8_t b[2];
  if (lerPid("010C", b, 2)) vRpm = (b[0] * 256.0 + b[1]) / 4.0; else { semResposta++; falhasCiclo++; }
  if (lerPid("010D", b, 1)) vVel = b[0]; else { semResposta++; falhasCiclo++; }
  if (lerPid("010B", b, 1)) vMap = b[0]; else { semResposta++; falhasCiclo++; }
  if (lerPid("0111", b, 1)) vTps = b[0] * 100.0 / 255.0; else { semResposta++; falhasCiclo++; }
  if (lerPid("0105", b, 1)) vTemp = b[0] - 40.0; else { semResposta++; falhasCiclo++; }
}

void lerLentos() {
  uint8_t b[2];
  if (lerPid("0104", b, 1)) vCarga = b[0] * 100.0 / 255.0; else { semResposta++; falhasCiclo++; }
  if (lerPid("010F", b, 1)) vAr = b[0] - 40.0; else { semResposta++; falhasCiclo++; }
  if (lerPid("0106", b, 1)) vStft = b[0]; else { semResposta++; falhasCiclo++; }
  if (lerPid("0107", b, 1)) vLtft = b[0]; else { semResposta++; falhasCiclo++; }
  if (lerPid("010E", b, 1)) vAvanc = b[0]; else { semResposta++; falhasCiclo++; }
  if (lerPid("0114", b, 2)) vO2a = b[0] * 0.005; else { semResposta++; falhasCiclo++; }
  if (lerPid("0115", b, 2)) vO2b = b[0] * 0.005; else { semResposta++; falhasCiclo++; }
  if (lerPid("0103", b, 1)) vFuel = b[0]; else { semResposta++; falhasCiclo++; }
}

void lerMil() {
  uint8_t b[2];
  if (lerPid("0101", b, 2)) {
    vMil = (b[0] & 0x80) ? 1 : 0;
    vDtc = b[0] & 0x7F;
  }
}

// ---------------------------------------------------------------- sync

bool enviado(const String &nome) {
  String ok = "/" + nome + ".ok";
  return LittleFS.exists(ok);
}

String listarPendentes() {
  String j = "{\"itens\":[";
  size_t total = 0;
  bool primeiro = true;
  File raiz = LittleFS.open("/");
  File f = raiz.openNextFile();
  while (f) {
    String n = f.name();
    if (n.startsWith("/")) n = n.substring(1);
    if (n.endsWith(".bin") || n.endsWith(".csv")) {
      bool ok = enviado(n);
      total += ok ? 0 : f.size();
      if (!primeiro) j += ",";
      j += "{\"f\":\"" + n + "\",\"kb\":" + String(f.size() / 1024) + ",\"ok\":" + (ok ? "true" : "false") + "}";
      primeiro = false;
    }
    f = raiz.openNextFile();
  }
  raiz.close();
  j += "],\"total_kb\":" + String(total / 1024) + "}";
  return j;
}

void marcar() {
  String n = web.arg("f");
  if (!n.length()) { web.send(400, "text/plain", "falta f"); return; }
  String ok = "/" + n + ".ok";
  File f = LittleFS.open(ok, FILE_WRITE);
  if (f) { f.print("1"); f.close(); }
  web.send(200, "application/json", "{\"ok\":true}");
}

void geo() {
  if (csv) {
    float lat = web.arg("lat").toFloat();
    float lon = web.arg("lon").toFloat();
    float alt = web.arg("alt").toFloat();
    if (lat != 0 || lon != 0) {
      csv.printf("# geo %ld %.6f %.6f %.1f\n", epochBase + (long)(millis() / 1000), lat, lon, alt);
      csv.flush();
    }
  }
  web.send(200, "application/json", "{\"ok\":true}");
}

void marcarHora(long ts) {
  epochBase = ts - (long)(millis() / 1000);
  if (csv) { csv.printf("# hora %ld %lu\n", ts, millis()); csv.flush(); }
  Serial.printf("hora sync: %ld\n", ts);
}

void servirLog() {
  String n = web.arg("f");
  if (!n.length()) n = arquivo;
  else n = "/" + n;
  if (n == arquivo && csv) csv.flush();
  File f = LittleFS.open(n, FILE_READ);
  if (!f) { web.send(404, "text/plain", "nao existe"); return; }
  String nome = n;
  if (nome.startsWith("/")) nome = nome.substring(1);
  web.sendHeader("Content-Disposition", "attachment; filename=" + nome);
  web.streamFile(f, "application/octet-stream");
  f.close();
}

String jsonEstado() {
  char b[420];
  snprintf(b, sizeof(b),
           "{\"rpm\":%.0f,\"vel\":%.0f,\"tps\":%.1f,\"carga\":%.1f,\"temp\":%.0f,\"ar\":%.0f,"
           "\"map\":%.0f,\"o2a\":%.2f,\"o2b\":%.2f,\"fuel\":%.0f,\"mil\":%d,\"dtc\":%d,"
           "\"falhas\":%d,\"ms\":%lu,\"hora\":%ld,\"arq\":\"%s\",\"su\":\"%s\",\"st\":\"%s\"}",
           vRpm, vVel, vTps, vCarga, vTemp, vAr, vMap, vO2a, vO2b, vFuel,
           vMil, vDtc, falhasCiclo, millis(), epochBase ? epochBase + (long)(millis() / 1000) : 0,
           arquivo.c_str(), SYNC_URL, SYNC_TOKEN);
  return String(b);
}

// ---------------------------------------------------------------- página

static const char PAGINA[] PROGMEM = R"HTML(<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Doblo</title>
<style>
:root{--bg:#0b0e12;--fg:#e8eef5;--dim:#8b97a5;--ok:#2ecc71;--warn:#f1c40f;--bad:#e74c3c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px system-ui,sans-serif}
#faixa{padding:12px;text-align:center;font-weight:700;background:var(--ok);color:#04120a}
.g{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:10px}
.c{background:#151b22;border-radius:14px;padding:14px}
.c b{display:block;font-size:46px;line-height:1;font-variant-numeric:tabular-nums}
.c span{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
#det{color:var(--dim);font:13px ui-monospace,monospace;padding:0 14px 12px;line-height:1.7;white-space:pre-line}
#sync{margin:0 10px 14px;background:#151b22;border-radius:14px;padding:12px;font-size:14px}
#sync b{color:var(--fg)}
button{background:#1f6feb;color:#fff;border:0;border-radius:10px;padding:9px 14px;font-size:14px}
a{color:#5dade2}
</style></head><body>
<div id=faixa>conectando...</div>
<div class=g>
<div class=c><span>temperatura</span><b id=temp>--</b></div>
<div class=c><span>rotacao</span><b id=rpm>--</b></div>
<div class=c><span>map</span><b id=map>--</b></div>
<div class=c><span>mistura</span><b id=fuel style="font-size:26px">--</b></div>
</div>
<div id=det>carregando...</div>
<div id=sync><b id=pend>verificando...</b><br><span id=sst style="color:#8b97a5"></span>
<div style="margin-top:8px"><button id=bt>enviar agora</button></div></div>
<script>
let S={}, ocupado=false;
const q=new URLSearchParams(location.search);
if(q.has('lat')) fetch('/geo?lat='+q.get('lat')+'&lon='+q.get('lon')+'&alt='+(q.get('alt')||0));
fetch('/hora?ts='+Math.floor(Date.now()/1000));
function enviar(f,dados,enc){
 return new Promise(res=>{
  const fr=document.createElement('iframe');fr.name='ifr_'+f.replace(/[^a-z0-9]/gi,'');fr.style.display='none';
  document.body.appendChild(fr);
  const fm=document.createElement('form');fm.method='POST';fm.target=fr.name;
  fm.action=S.su+'?token='+encodeURIComponent(S.st)+'&trip='+encodeURIComponent(f)+'&off=0&total='+dados.length+'&enc='+enc;
  const ta=document.createElement('textarea');ta.name='data';ta.value=dados;
  fm.appendChild(ta);document.body.appendChild(fm);
  let feito=false;
  fr.onload=()=>{ if(!feito){feito=true;setTimeout(()=>{fm.remove();fr.remove();res(true)},200);} };
  fm.submit();
  setTimeout(()=>{ if(!feito){feito=true;fm.remove();fr.remove();res(false);} },25000);
 });
}
function b64(bytes){
 const CH=0x8000; let s='';
 for(let i=0;i<bytes.length;i+=CH) s+=String.fromCharCode.apply(null,bytes.subarray(i,i+CH));
 return btoa(s);
}
async function sincronizar(){
 if(ocupado)return; ocupado=true;
 try{
  const r=await (await fetch('/pendentes')).json();
  const falta=r.itens.filter(i=>!i.ok);
  document.getElementById('pend').textContent=falta.length?falta.length+' viagem(ns) pendente(s) - '+Math.round(r.total_kb)+' KB':'nada pendente';
  for(const it of falta){
   document.getElementById('sst').textContent='enviando '+it.f+' ...';
   const buf=new Uint8Array(await (await fetch('/log?f='+encodeURIComponent(it.f))).arrayBuffer());
   const ok=await enviar(it.f, b64(buf), 'b64');
   if(ok){ await fetch('/marcar?f='+encodeURIComponent(it.f)); document.getElementById('sst').textContent='enviado '+it.f; }
   else { document.getElementById('sst').textContent='falhou '+it.f+' (tenta de novo)'; break; }
  }
 }catch(e){ document.getElementById('sst').textContent='sem conexao com a placa'; }
 ocupado=false;
}
document.getElementById('bt').onclick=sincronizar;
async function t(){
 try{
  const s=await (await fetch('/api')).json(); S=s;
  temp.textContent=(s.temp>=0?s.temp.toFixed(0)+' C':'--');
  rpm.textContent=(s.rpm>=0?s.rpm.toFixed(0):'--');
  map.textContent=(s.map>=0?s.map.toFixed(0)+' kPa':'--');
  fuel.textContent=(s.fuel==2?'fechada':(s.fuel==1?'aberta':'--'));
  const f=document.getElementById('faixa');
  if(s.temp>=108){f.textContent='PARE - TEMPERATURA ALTA';f.style.background='var(--bad)';}
  else if(s.temp>=102){f.textContent='ATENCAO - TEMPERATURA';f.style.background='var(--warn)';}
  else{f.textContent='normal';f.style.background='var(--ok)';}
  det.textContent='tps '+s.tps.toFixed(1)+'%  carga '+s.carga.toFixed(1)+'%  ar '+s.ar.toFixed(0)+'C  sonda '+s.o2a.toFixed(2)+'/'+s.o2b.toFixed(2)+' V\n'+
    'falhas '+s.falhas+'  dtc '+s.dtc+(s.mil?'  MIL ACESO':'')+'  '+(s.hora?new Date(s.hora*1000).toLocaleString():'sem hora');
 }catch(e){document.getElementById('faixa').textContent='sem conexao';}
 setTimeout(t,1000);
}
t();
setTimeout(sincronizar,1500);
</script></body></html>)HTML";

// ---------------------------------------------------------------- rede

bool staAvisado = false;

void iniciarRede() {
  // AP sobe SEMPRE e imediatamente; a estacao de casa tenta em paralelo.
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.printf("AP %s  ip %s\n", AP_SSID, WiFi.softAPIP().toString().c_str());
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  web.on("/", HTTP_GET, []() { web.send_P(200, "text/html", PAGINA); });
  web.on("/api", HTTP_GET, []() { web.send(200, "application/json", jsonEstado()); });
  web.on("/log", HTTP_GET, servirLog);
  web.on("/pendentes", HTTP_GET, []() { web.send(200, "application/json", listarPendentes()); });
  web.on("/marcar", HTTP_GET, marcar);
  web.on("/geo", HTTP_GET, geo);
  web.on("/hora", HTTP_GET, []() {
    long ts = web.arg("ts").toInt();
    if (ts > 1700000000) marcarHora(ts);
    web.send(200, "application/json", "{}");
  });
  web.begin();
  Serial.println("http pronto");
}

// ---------------------------------------------------------------- serial

void despejarCsv() {
  if (!gravando) { Serial.println("sem arquivo"); return; }
  csv.flush();
  File f = LittleFS.open(arquivo, FILE_READ);
  if (!f) { Serial.println("nao abriu"); return; }
  unsigned tam = f.size();
  f.close();
  Serial.printf("--- %s: %u bytes, %u amostras ---\n", arquivo.c_str(), tam, (tam - 4) / 20);
}

void status() {
  Serial.printf("arquivo %s | ciclos %lu | falhas %lu | fs %u/%u KB\n",
                arquivo.c_str(), ciclos, semResposta,
                (unsigned)(LittleFS.usedBytes() / 1024),
                (unsigned)(LittleFS.totalBytes() / 1024));
}

void tratarSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'd' || c == 'D') despejarCsv();
    if (c == 's' || c == 'S') status();
  }
}

// ---------------------------------------------------------------- setup

void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println("\n== doblo logger + painel ==");
  pinMode(PINO_BUZ, OUTPUT);
  digitalWrite(PINO_BUZ, LOW);

  prefs.begin("doblo", false);
  if (!LittleFS.begin(true)) Serial.println("LittleFS falhou");

  iniciarRede();  // AP primeiro: a rede tem que existir em ~1 s

  Serial.println("[1/6] bluetooth");
  if (!conectarDongle()) {
    Serial.println("  FALHOU: dongle nao respondeu");
    Serial.println("  -> chave ligada? algum celular conectado nele?");
  } else {
    Serial.println("  ok");
    Serial.printf("[2/6] ATZ   : %s\n", at("ATZ", 4000).c_str());
    Serial.println("[3/6] ATE0/ATL0/ATS0");
    at("ATE0"); at("ATL0"); at("ATS0");
    Serial.println("[4/6] ATSP5 (KWP fast)");
    Serial.printf("  -> %s\n", at("ATSP5", 1500).c_str());
    uint8_t b[4];
    Serial.println("[5/6] 0100 (bus init da K-line)");
    if (lerPid("0100", b, 4, 8000)) Serial.println("  ok: ECU respondeu");
    else Serial.println("  FALHOU: ECU muda (chave so no acessorio? central dormindo?)");
    abrirCsv();
    gravarDtc();
    lerMil();
    Serial.println("[6/6] pronto");
  }
}

// ---------------------------------------------------------------- loop

void loop() {
  tratarSerial();
  web.handleClient();
  if (!staAvisado && WiFi.status() == WL_CONNECTED) {
    staAvisado = true;
    Serial.printf("wifi casa: %s rssi %d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  }
  if (!gravando) { delay(200); return; }

  if (millis() - tUltimoCiclo >= CICLO_MS) {
    tUltimoCiclo = millis();
    lerRapidos();
    if (ciclos % 4 == 0) lerLentos();
    if (ciclos % 20 == 0) lerMil();
    gravarLinha();
    ciclos++;

    if (falhasCiclo >= 5) falhasSeguidas++; else falhasSeguidas = 0;
    if (falhasSeguidas > 5) { reinitElm(); falhasSeguidas = 0; }
    falhasCiclo = 0;

    if (ciclos % 5 == 0)
      Serial.printf("%5.0f rpm %3.0f km/h %4.1f C %3.0f kPa\n", vRpm, vVel, vTemp, vMap);

    if (vTemp > 108) digitalWrite(PINO_BUZ, HIGH);
    else if (vTemp > 102) digitalWrite(PINO_BUZ, (millis() / 500) % 2);
    else digitalWrite(PINO_BUZ, LOW);
  }
}
