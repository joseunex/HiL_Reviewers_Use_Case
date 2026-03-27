// --------------------------------------------------------------------------------------------------------------------------------

#include <TinkerKit.h>
#include <PubSubClient.h>
#include <YunClient.h>

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
    var = potR.read();
    var = "{ \"value\" : \"" + var + "\" }";

    // Publish the sensor value:
    mqtt_foga0.publish(TOPIC_c, (char*) var.c_str());

    // Wait 1000 milliseconds before the next loop
    delay(1000);
  }

  mqtt_foga0.loop();
}

// --------------------------------------------------------------------------------------------------------------------------------
