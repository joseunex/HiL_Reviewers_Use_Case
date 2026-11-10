// --------------------------------------------------------------------------------------------------------------------------------

#include <TinkerKit.h>
#include <PubSubClient.h>
#include <YunClient.h>
#include <Process.h>

// --------------------------------------------------------------------------------------------------------------------------------
// MQTT endpoint for external (LAN) access:
//
// - Mosquitto runs inside Kubernetes (per fog).
// - Each Mosquitto exposes a NodePort service: 30100 + fogId
// - Arduino is outside the cluster, so it cannot use in-cluster DNS.
// - We therefore connect to the host/entrypoint IP (same IP used by the registry).
//
// IMPORTANT: macro identifiers must be valid C identifiers, so we sanitize names to [A-Za-z0-9_].

// --------------------------------------------------------------------------------------------------------------------------------

#define MQTT_HOST_foga0 "192.168.0.17"
#define PORT_foga0 30100

#define TOPIC_c "C"

#define SERIAL 9600

#define SENSOR_ID "sensthread1"
#define CLOCK_SAMPLES 6             // Exchanges per clock synchronization
#define CLOCK_RESYNC_MS 30000UL     // Clock resynchronization period (ms)

// --------------------------------------------------------------------------------------------------------------------------------

void callback(char* topic, byte* payload, unsigned int length) {
  // Handle message arrived (not used for sensor-only publisher)
}

// --------------------------------------------------------------------------------------------------------------------------------

YunClient yun;
PubSubClient mqtt_foga0(MQTT_HOST_foga0, PORT_foga0, callback, yun);

boolean connected = false;   // Toggle connected variable to check if MQTT is running

TKPotentiometer potR(I0);    // Creating the object 'potR' (TKPotentiometer class). Hooked up on I0

String var;                 // Auxiliary string variable
unsigned long seq = 0;      // Monotonic sequence number (seq)

// --------------------------------------------------------------------------------------------------------------------------------
// Global timestamp (tg): Unix time in ms, which needs 64 bits (unsigned long has
// 32 on the AVR). The sketch keeps the Unix time of its last synchronization with
// the NTP-aligned clock of the Linux side of the Yun and adds the milliseconds
// elapsed since then. Each synchronization makes several exchanges through the
// Bridge and keeps the one with the lowest round trip (Cristian's algorithm), so
// the uncertainty of tg is half that round trip plus the NTP error.

// Python helper on the Linux side: answers each line with the Unix time in ms
#define CLOCK_HELPER "import sys,time;[sys.stdout.write('%d\\n'%int(time.time()*1000))" \
                     " for l in iter(sys.stdin.readline,'')]"

Process clockProc;                  // Runs CLOCK_HELPER on the Linux side
uint64_t syncEpochMs = 0;           // Unix time (ms) at lastSyncMillis
unsigned long lastSyncMillis = 0;   // millis() at the last synchronization
unsigned long lastSyncAttempt = 0;  // millis() at the last attempt
unsigned int clockRtt = 0;          // Round trip of the last sync (ms)

uint64_t nowEpochMs() {
  // Unsigned difference: also valid when millis() wraps around (49.7 days)
  return syncEpochMs + (unsigned long)(millis() - lastSyncMillis);
}

uint64_t parseU64(const char* s) {
  uint64_t v = 0;
  while (*s >= '0' && *s <= '9') v = v * 10 + (uint64_t)(*s++ - '0');
  return v;
}

// Writes a 64-bit unsigned integer in decimal (AVR printf lacks %llu)
void u64ToStr(char* out, uint64_t v) {
  char b[21];
  int i = 20;
  b[i] = 0;
  do { b[--i] = '0' + (char)(v % 10); v /= 10; } while (v > 0);
  strcpy(out, b + i);
}

bool readClockLine(char* buf, size_t n, unsigned long timeoutMs) {
  unsigned long t0 = millis();
  size_t i = 0;
  while (millis() - t0 < timeoutMs) {
    while (clockProc.available()) {
      char c = clockProc.read();
      if (c == '\n') { buf[i] = 0; return i > 0; }
      if (c != '\r' && i < n - 1) buf[i++] = c;
    }
  }
  return false;
}

bool syncClock() {
  if (!clockProc.running()) {
    clockProc.begin("python");
    clockProc.addParameter("-u");
    clockProc.addParameter("-c");
    clockProc.addParameter(CLOCK_HELPER);
    clockProc.runAsynchronously();
    delay(3000);                      // Python takes a few seconds to start
  }
  char buf[24];
  unsigned int bestRtt = 0xFFFF;
  for (int k = 0; k < CLOCK_SAMPLES; k++) {
    unsigned long t0 = millis();
    clockProc.print('\n');            // The helper answers with the Unix time
    if (!readClockLine(buf, sizeof(buf), 1000)) continue;
    unsigned int rtt = (unsigned int)(millis() - t0);
    uint64_t linuxMs = parseU64(buf);
    // Skip answers that are not Unix times in ms and slower exchanges
    if (linuxMs < 1000000000000ULL || rtt >= bestRtt) continue;
    bestRtt = rtt;
    syncEpochMs = linuxMs;            // Assigned to the midpoint of the exchange
    lastSyncMillis = t0 + rtt / 2;
  }
  if (bestRtt == 0xFFFF) return false;
  clockRtt = bestRtt;
  return true;
}

// --------------------------------------------------------------------------------------------------------------------------------
// Payload expected by the CEP: {"id","seq","tg","val","clk_rtt_ms"}. val is a JSON
// number when the reading is numeric and a string otherwise (several axes).

bool isNumber(const String& s) {
  unsigned int i = (s.length() > 0 && s.charAt(0) == '-') ? 1 : 0;
  bool digits = false, dot = false;
  for (; i < s.length(); i++) {
    char c = s.charAt(i);
    if (isDigit(c)) digits = true;
    else if (c == '.' && !dot) dot = true;
    else return false;
  }
  return digits;
}

void buildPayload(char* out, size_t n, uint64_t tg) {
  char tgStr[21];
  u64ToStr(tgStr, tg);
  const char* q = isNumber(var) ? "" : "\"";
  snprintf(out, n, "{\"id\":\"%s\",\"seq\":%lu,\"tg\":%s,\"val\":%s%s%s,\"clk_rtt_ms\":%u}",
           SENSOR_ID, seq, tgStr, q, var.c_str(), q, clockRtt);
}

// --------------------------------------------------------------------------------------------------------------------------------

void connectMQTT(){
  while(!connected){
    if (mqtt_foga0.connect("sensor1_foga0")) {
      connected = true;
    }
    else {
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(SERIAL);
  Bridge.begin();
  while (!syncClock()) delay(1000);   // Synchronized clock before the first tg
  lastSyncAttempt = millis();
  connectMQTT();
}

// --------------------------------------------------------------------------------------------------------------------------------

void loop() {
  if (!mqtt_foga0.connected()) {
    connected = false;
    connectMQTT();
  }
  else {
    // Read the sensor value:
    var = String(potR.read());
    // tg and seq support CEP-side ordering and bounded-lateness validation
    char payload[128];
    buildPayload(payload, sizeof(payload), nowEpochMs());
    seq++;

    // Publish the sensor value:
    mqtt_foga0.publish(TOPIC_c, payload);

    // Resynchronize the clock with the Linux side every CLOCK_RESYNC_MS
    if (millis() - lastSyncAttempt > CLOCK_RESYNC_MS) {
      lastSyncAttempt = millis();
      syncClock();
    }

    // Wait 1000 milliseconds before the next loop
    delay(1000);
  }

  mqtt_foga0.loop();
}

// --------------------------------------------------------------------------------------------------------------------------------
