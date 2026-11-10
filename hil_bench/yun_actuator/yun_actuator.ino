// --------------------------------------------------------------------------------------------------------------------------------
// HiL actuator of the bench (Arduino Yún): cooling valve of the batch reactor (use case 2).
//
// Same contract as the containerised actuator acta0, so that the rest of the system does not change:
//   - it subscribes to topic B, where the CEP publishes the ON/OFF commands;
//   - it applies the command on a physical output: TinkerKit module on O0 (relay or LED) and also the on-board LED L13;
//   - it publishes the ACK on actuators/ack with the same JSON as acta0 (the loop sensor reads applied_state and
//     analyze_experiment.py reads the actuator timestamps).
// Differences with acta0:
//   - t_act_act is the instant at which the microcontroller writes the output (effective actuation);
//   - the timestamps are 64-bit (milliseconds of the Unix epoch). The clock of the microcontroller is synchronised
//     every 30 s with the Linux side of the Yún (NTP-aligned with the host): several exchanges are made and the one
//     with the shortest round trip is kept (Cristian's algorithm). That round trip goes in the ACK (clk_rtt_ms):
//     the uncertainty of the clock is ±clk_rtt_ms/2 plus the NTP error.
// Style and libraries of the code that SimulateIoT generates for Arduino nodes (PubSubClient over YunClient, TinkerKit).
// Before uploading, set MQTT_HOST_foga0 to the IP of the host that exposes the Mosquitto NodePort (hil_bench/bench.env).
// --------------------------------------------------------------------------------------------------------------------------------

#include <Bridge.h>
#include <Process.h>
#include <YunClient.h>
#include <PubSubClient.h>
#include <TinkerKit.h>

// MQTT broker of Fog foga0: the Mosquitto of the cluster, exposed as a NodePort on the IP of the host
#define MQTT_HOST_foga0 "BROKER_IP"
#define PORT_foga0 30100

#define TOPIC_cmd "B"
#define TOPIC_ack "actuators/ack"
#define ACTUATOR_ID "yun_acta0"

#define MQTT_BUFFER 384            // the CEP commands take about 250 bytes
#define CLOCK_RESYNC_MS 30000UL    // clock resynchronisation period
#define CLOCK_SAMPLES 6            // exchanges per synchronisation (the one with the shortest round trip is kept)
#define BOARD_LED 13

// --------------------------------------------------------------------------------------------------------------------------------

void callback(char* topic, byte* payload, unsigned int length);

YunClient yun;
PubSubClient mqtt_foga0(MQTT_HOST_foga0, PORT_foga0, callback, yun);
TKRelay valve(O0);                 // valve: TinkerKit module on O0
bool valveOn = false;

Process clockProc;                 // /root/hil_clock.py on the Linux side of the Yún
int64_t clockOffset = 0;           // epoch (ms) = millis() + clockOffset
unsigned int clockRtt = 0;         // round trip of the last synchronisation (ms)
unsigned long lastSyncMillis = 0;
unsigned long lastCmdMillis = 0;

// Fields of the ACK. Declared up here because the Arduino preprocessor inserts the function prototypes
// before the first function of the sketch, and writeAck() uses this type.
struct Ack {
  bool parsedOk;
  const char* desired;
  const char* applied;
  const char* id;
  const char* seq;
  const char* tg;
  const char* val;
  const char* tsr;
  const char* tsn;
  const char* drops;
  uint64_t tCmdRcv;
  uint64_t tAct;
  uint64_t tAckPub;
  unsigned long clkAge;   // age of the last clock synchronisation, set once (see writeAck)
};

uint64_t nowEpochMs() {
  return (uint64_t)((int64_t)millis() + clockOffset);
}

// --------------------------------------------------------------------------------------------------------------------------------
// Utilities

// Writes a 64-bit integer in decimal (Arduino's print() does not support them)
void printU64(Print& p, uint64_t v) {
  char b[21];
  int i = 20;
  b[i] = 0;
  if (v == 0) b[--i] = '0';
  while (v > 0 && i > 0) {
    b[--i] = '0' + (char)(v % 10);
    v /= 10;
  }
  p.print(b + i);
}

uint64_t parseU64(const char* s) {
  uint64_t v = 0;
  while (*s >= '0' && *s <= '9') {
    v = v * 10 + (uint64_t)(*s - '0');
    s++;
  }
  return v;
}

// Copies into out the value of "key" of the JSON js[0..len): without quotes if it is a string; verbatim if it is
// a number, a boolean or an object {...}. Returns false if the key is missing.
bool jsonRaw(const char* js, unsigned int len, const char* key, char* out, size_t outLen) {
  size_t klen = strlen(key);
  out[0] = 0;
  for (unsigned int i = 0; i + klen + 2 < len; i++) {
    if (js[i] != '"' || strncmp(js + i + 1, key, klen) != 0 || js[i + 1 + klen] != '"') continue;
    unsigned int j = i + klen + 2;
    while (j < len && (js[j] == ' ' || js[j] == ':')) j++;
    if (j >= len) return false;
    size_t o = 0;
    if (js[j] == '"') {
      j++;
      while (j < len && js[j] != '"' && o < outLen - 1) out[o++] = js[j++];
    } else if (js[j] == '{') {
      int depth = 0;
      while (j < len && o < outLen - 1) {
        char c = js[j++];
        out[o++] = c;
        if (c == '{') depth++;
        else if (c == '}' && --depth == 0) break;
      }
    } else {
      while (j < len && js[j] != ',' && js[j] != '}' && js[j] != ' ' && o < outLen - 1) out[o++] = js[j++];
    }
    out[o] = 0;
    return o > 0;
  }
  return false;
}

// Counts bytes without writing them (to know the length of the ACK before publishing it)
class CountPrint : public Print {
 public:
  size_t n = 0;
  size_t write(uint8_t) { n++; return 1; }
};

// Sends to the MQTT client in chunks: every write is a transaction of the bridge with the Linux side of the Yún
// (about 20 ms), so few of them are better. With 192-byte chunks the ACK (about 730 bytes) takes 4 writes instead of 12.
#define ACK_CHUNK 192
class ChunkPrint : public Print {
 public:
  ChunkPrint(PubSubClient& m) : m_(m), n_(0) {}
  size_t write(uint8_t c) {
    b_[n_++] = c;
    if (n_ == sizeof(b_)) flush();
    return 1;
  }
  void flush() {
    if (n_ > 0) m_.write(b_, n_);
    n_ = 0;
  }
 private:
  PubSubClient& m_;
  uint8_t b_[ACK_CHUNK];
  size_t n_;
};

// --------------------------------------------------------------------------------------------------------------------------------
// Clock: synchronisation with the Linux side of the Yún

bool readLine(Process& p, char* buf, size_t n, unsigned long timeoutMs) {
  unsigned long t0 = millis();
  size_t i = 0;
  while (millis() - t0 < timeoutMs) {
    while (p.available()) {
      char c = p.read();
      if (c == '\n') { buf[i] = 0; return i > 0; }
      if (c != '\r' && i < n - 1) buf[i++] = c;
    }
  }
  buf[i] = 0;
  return false;
}

bool syncClock() {
  if (!clockProc.running()) {
    clockProc.begin("python");
    clockProc.addParameter("-u");
    clockProc.addParameter("/root/hil_clock.py");
    clockProc.runAsynchronously();
    delay(3000);                   // python takes a while to start on the Yún
  }
  char buf[24];
  unsigned int bestRtt = 0xFFFF;
  int64_t bestOffset = 0;
  for (int k = 0; k < CLOCK_SAMPLES; k++) {
    unsigned long t0 = millis();
    clockProc.print('\n');
    if (!readLine(clockProc, buf, sizeof(buf), 1000)) continue;
    unsigned int rtt = (unsigned int)(millis() - t0);
    uint64_t linuxMs = parseU64(buf);
    if (linuxMs < 1000000000000ULL) continue;   // not a time in milliseconds
    if (rtt < bestRtt) {
      bestRtt = rtt;
      bestOffset = (int64_t)linuxMs - (int64_t)(t0 + rtt / 2);
    }
  }
  if (bestRtt == 0xFFFF) return false;
  clockOffset = bestOffset;
  clockRtt = bestRtt;
  lastSyncMillis = millis();
  return true;
}

// --------------------------------------------------------------------------------------------------------------------------------
// ACK (same JSON as acta0, plus clk_rtt_ms, clk_age_ms and hw)

void field(Print& p, bool& first, const __FlashStringHelper* name, const char* raw, bool quoted) {
  if (raw == NULL || raw[0] == 0) return;
  if (!first) p.print(',');
  first = false;
  p.print('"'); p.print(name); p.print(F("\":"));
  if (quoted) p.print('"');
  p.print(raw);
  if (quoted) p.print('"');
}

void fieldU64(Print& p, const __FlashStringHelper* name, uint64_t v) {
  p.print(F(",\"")); p.print(name); p.print(F("\":"));
  printU64(p, v);
}

void writeAck(Print& p, const Ack& a) {
  bool first;
  p.print(F("{\"type\":\"actuator_ack\",\"cmd_id\":\""));
  p.print(a.id[0] ? a.id : "yun_cmd");
  p.print(F("\",\"parsed_ok\":"));
  p.print(a.parsedOk ? F("true") : F("false"));
  p.print(F(",\"sensor\":{"));
  first = true;
  field(p, first, F("id"), a.id, true);
  field(p, first, F("seq"), a.seq, false);
  field(p, first, F("tg"), a.tg, false);
  field(p, first, F("val"), a.val, false);
  p.print(F("},\"cep\":{"));
  first = true;
  field(p, first, F("tsr_esper"), a.tsr, false);
  field(p, first, F("tsn_esper"), a.tsn, false);
  field(p, first, F("cep_drops"), a.drops, false);
  p.print(F("},\"actuator\":{\"id\":\"" ACTUATOR_ID "\",\"hw\":\"arduino_yun\",\"cmd_topic\":\"" TOPIC_cmd
            "\",\"ack_topic\":\"" TOPIC_ack "\",\"desired_state\":\""));
  p.print(a.desired);
  p.print(F("\",\"applied_state\":\""));
  p.print(a.applied);
  p.print('"');
  fieldU64(p, F("t_cmd_rcv_act"), a.tCmdRcv);
  fieldU64(p, F("t_act_act"), a.tAct);
  fieldU64(p, F("t_ack_pub_act"), a.tAckPub);
  p.print(F(",\"clk_rtt_ms\":"));
  p.print(clockRtt);
  p.print(F(",\"clk_age_ms\":"));
  p.print(a.clkAge);   // not millis() here: writeAck runs twice (count and send) and the lengths must match
  p.print(F("}}"));
}

// --------------------------------------------------------------------------------------------------------------------------------
// Command received from the CEP

void callback(char* topic, byte* payload, unsigned int length) {
  uint64_t tCmdRcv = nowEpochMs();
  lastCmdMillis = millis();

  // Copy of the fields before publishing: PubSubClient reuses its buffer when the ACK is published
  const char* js = (const char*)payload;
  char msg[8], id[40], seq[12], tg[16], val[16], tsr[16], tsn[16], drops[96];
  bool hasMsg = jsonRaw(js, length, "msg", msg, sizeof(msg));
  jsonRaw(js, length, "id", id, sizeof(id));
  jsonRaw(js, length, "seq", seq, sizeof(seq));
  jsonRaw(js, length, "tg", tg, sizeof(tg));
  jsonRaw(js, length, "val", val, sizeof(val));
  jsonRaw(js, length, "tsr_esper", tsr, sizeof(tsr));
  jsonRaw(js, length, "tsn_esper", tsn, sizeof(tsn));
  jsonRaw(js, length, "cep_drops", drops, sizeof(drops));

  bool on = hasMsg && strcmp(msg, "ON") == 0;
  bool off = hasMsg && strcmp(msg, "OFF") == 0;
  if (on) {
    valve.on();
    digitalWrite(BOARD_LED, HIGH);
    valveOn = true;
  } else if (off) {
    valve.off();
    digitalWrite(BOARD_LED, LOW);
    valveOn = false;
  }
  uint64_t tAct = nowEpochMs();    // effective actuation: the output has been written

  Ack a;
  a.parsedOk = on || off;
  a.desired = hasMsg ? msg : "";
  a.applied = valveOn ? "ON" : "OFF";
  a.id = id; a.seq = seq; a.tg = tg; a.val = val;
  a.tsr = tsr; a.tsn = tsn; a.drops = drops;
  a.tCmdRcv = tCmdRcv;
  a.tAct = tAct;
  a.tAckPub = nowEpochMs();        // as in acta0: the instant at which the ACK is handed to the MQTT client
  a.clkAge = millis() - lastSyncMillis;

  CountPrint cp;
  writeAck(cp, a);
  if (mqtt_foga0.beginPublish(TOPIC_ack, cp.n, false)) {
    ChunkPrint out(mqtt_foga0);
    writeAck(out, a);
    out.flush();
    mqtt_foga0.endPublish();
  }
}

// --------------------------------------------------------------------------------------------------------------------------------

void connectMQTT() {
  while (!mqtt_foga0.connected()) {
    if (mqtt_foga0.connect(ACTUATOR_ID)) {
      mqtt_foga0.subscribe(TOPIC_cmd);
    } else {
      delay(5000);
    }
  }
}

void setup() {
  pinMode(BOARD_LED, OUTPUT);
  digitalWrite(BOARD_LED, LOW);
  valve.off();                     // valve closed at start-up
  Bridge.begin();                  // bridge with the Linux side of the Yún (takes a few seconds)
  while (!syncClock()) delay(1000);
  mqtt_foga0.setBufferSize(MQTT_BUFFER);
  connectMQTT();
}

void loop() {
  if (!mqtt_foga0.connected()) connectMQTT();
  mqtt_foga0.loop();
  // Resynchronise the clock every 30 s, but not right after a command (at most one per second arrives)
  if (millis() - lastSyncMillis > CLOCK_RESYNC_MS && millis() - lastCmdMillis > 150) syncClock();
}

// --------------------------------------------------------------------------------------------------------------------------------
