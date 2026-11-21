// Passo 2: descobre dispositivos BT à vista, escolhe o dongle pelo nome e
// tenta falar AT. Saída no monitor serial 115200.

#include <BluetoothSerial.h>

BluetoothSerial SerialBT;
const char *MAC_FALLBACK = "01:23:45:67:89:BA";

String cmd(const char *c, uint32_t timeout = 3000) {
  while (SerialBT.available()) SerialBT.read();
  SerialBT.write((const uint8_t *)c, strlen(c));
  SerialBT.write('\r');
  String r;
  uint32_t t0 = millis();
  while (millis() - t0 < timeout) {
    if (SerialBT.available()) {
      char ch = SerialBT.read();
      if (ch == '>') break;
      if (ch != '\r') r += ch;
    }
    delay(2);
  }
  r.trim();
  Serial.printf("%-8s -> %s\n", c, r.c_str());
  return r;
}

bool pareceDongle(String nome) {
  nome.toUpperCase();
  return nome.indexOf("OBD") >= 0 || nome.indexOf("ELM") >= 0 ||
         nome.indexOf("V-LINK") >= 0 || nome.indexOf("VLINK") >= 0;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n== 1) descobrindo Bluetooth ==");

  SerialBT.begin("ESP32-OBD", true);
  delay(1500);
  Serial.printf("meu MAC BT: %s\n", SerialBT.getBtAddressString().c_str());

  BTAddress alvo;
  bool achou = false;
  BTScanResults *res = SerialBT.discover(12000);
  if (res) {
    Serial.printf("dispositivos: %d\n", res->getCount());
    for (int i = 0; i < res->getCount(); i++) {
      BTAdvertisedDevice *d = res->getDevice(i);
      if (!d) continue;
      String nome = String(d->getName().c_str());
      String addr = d->getAddress().toString().c_str();
      Serial.printf("  [%d] %-20s %s  rssi %d\n", i,
                    nome.length() ? nome.c_str() : "(sem nome)", addr.c_str(),
                    d->getRSSI());
      if (!achou && pareceDongle(nome)) {
        alvo = d->getAddress();
        achou = true;
        Serial.printf("  -> escolhido: %s (%s)\n", nome.c_str(), addr.c_str());
      }
    }
  } else {
    Serial.println("busca falhou");
  }
  if (!achou) {
    Serial.println("nenhum dongle pelo nome; usando MAC conhecido");
    alvo = BTAddress(MAC_FALLBACK);
  }

  Serial.println("\n== 2) conectando ==");
  SerialBT.setPin("1234", 4); // ELM327 clone pareia com PIN 1234
  bool ok = false;
  for (int i = 0; i < 2 && !ok; i++) {
    Serial.printf("tentativa %d...\n", i + 1);
    ok = SerialBT.connect(alvo);
    if (!ok) delay(1500);
  }
  if (!ok) {
    Serial.println("FALHOU: dongle energizado? algum celular conectado nele?");
    return;
  }
  Serial.println("conectado!");

  cmd("ATZ", 4000);
  cmd("ATI");
  cmd("ATE0");
  cmd("ATL0");
  cmd("ATS0");
  cmd("ATSP5", 1500);
  cmd("0100", 8000);
  for (int i = 0; i < 3; i++) {
    cmd("010C", 4000);
    delay(200);
  }
  cmd("0105");
  Serial.println("== fim ==");
}

void loop() {
  delay(1000);
}
