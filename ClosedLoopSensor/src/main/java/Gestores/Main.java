package Gestores;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicBoolean;
import org.eclipse.paho.client.mqttv3.MqttClient;
import java.time.Instant;

/**
 * Sensor de lazo cerrado con modelo térmico de reactor batch exotérmico.
 *
 * Modelo:
 *   T[k+1] = T[k] + dt * (Q_reac - coolingOn * Q_cool - k_loss * (T[k] - T_amb))
 *
 * El estado de refrigeración (coolingOn) se actualiza desde el Receiver
 * al recibir ACKs del actuador en el topic "actuators/ack".
 *
 * Banda de control: 78-82 °C (gestionada por el CEP, no por este sensor).
 * El sensor solo calcula la temperatura y la publica.
 */
public class Main {

    // ---- Parámetros del modelo térmico (reactor batch exotérmico) ----
    private static final double Q_REAC  = 0.15;   // °C/s - calor exotérmico normalizado
    private static final double Q_COOL  = 0.30;   // °C/s - capacidad de extracción de la camisa
    private static final double K_LOSS  = 0.001;  // 1/s  - coef. pérdidas térmicas al ambiente
    private static final double T_AMB   = 20.0;   // °C   - temperatura ambiente nave industrial
    private static final double T_INIT  = 78.0;   // °C   - temperatura inicial (límite inferior banda)

    private static String getenvOrDefault(String key, String defaultValue) {
        String v = System.getenv(key);
        return (v == null || v.trim().isEmpty()) ? defaultValue : v.trim();
    }

    private static int getenvIntOrDefault(String key, int defaultValue) {
        String v = System.getenv(key);
        if (v == null || v.trim().isEmpty()) return defaultValue;
        try {
            return Integer.parseInt(v.trim());
        } catch (NumberFormatException ex) {
            System.err.println("Invalid integer for env " + key + ": '" + v + "'. Using default=" + defaultValue);
            return defaultValue;
        }
    }

    private static String jsonEscape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    // ---- Estado compartido entre Receiver (callback MQTT) y SensorThread ----
    // coolingOn == true  → refrigeración activa  (válvula abierta)
    // coolingOn == false → refrigeración inactiva (válvula cerrada)
    private static final AtomicBoolean coolingOn = new AtomicBoolean(false);

    // ---- Hilo del sensor con modelo térmico ----
    static class SensorThread implements Runnable {
        private final String mqttBrokerUri;
        private final String mqttTopicName;
        private final String sensorId;
        private final int publishCount;
        private final long intervalMs;
        private final double dtSeconds;

        SensorThread(String mqttBrokerUri, String mqttTopicName, String sensorId,
                     int publishCount, long intervalMs) {
            this.mqttBrokerUri  = mqttBrokerUri;
            this.mqttTopicName  = mqttTopicName;
            this.sensorId       = sensorId;
            this.publishCount   = publishCount;
            this.intervalMs     = intervalMs;
            this.dtSeconds      = intervalMs / 1000.0;
        }

        @Override
        public void run() {
            // Conexión MQTT propia del hilo sensor
            List<Topic> Ltopic = new ArrayList<Topic>();
            // Topic de publicación: temperatura del reactor
            Ltopic.add(new Topic(mqttTopicName, false, true));
            // Topic de suscripción: ACKs del actuador (para cerrar el lazo)
            Ltopic.add(new Topic("actuators/ack", true, false));

            List<Broker> Lbroker = new ArrayList<Broker>();
            Lbroker.add(new Broker(mqttBrokerUri, Ltopic));

            GestorDeConexiones gestorconexiones = new GestorDeConexiones(sensorId, Lbroker);
            gestorconexiones.Iniciar();
            Publisher publisher = new Publisher();
            new Receiver(gestorconexiones, publisher, coolingOn);

            List<MqttClient> Lclient = gestorconexiones.getLclient();

            System.out.println("CLOSED_LOOP_SENSOR | started"
                    + " | sensor_id=" + sensorId
                    + " | broker=" + mqttBrokerUri
                    + " | topic=" + mqttTopicName
                    + " | publish_count=" + publishCount
                    + " | interval_ms=" + intervalMs
                    + " | T_init=" + T_INIT
                    + " | Q_reac=" + Q_REAC
                    + " | Q_cool=" + Q_COOL);

            // ---- Estado interno del modelo térmico ----
            double currentTemp = T_INIT;

            long nextPublishMs = (System.nanoTime() / 1_000_000L) + intervalMs;
            long seq = 0L;

            for (int i = 0; i < publishCount; i++) {

                // ---- Espera hasta el siguiente tick ----
                long nowMs = System.nanoTime() / 1_000_000L;
                long sleepMs = nextPublishMs - nowMs;
                if (sleepMs > 0) {
                    try { Thread.sleep(sleepMs); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                }

                long actualMs = System.nanoTime() / 1_000_000L;
                long latMs = Math.max(0L, actualMs - nextPublishMs);
                nextPublishMs += intervalMs;

                // ---- Leer estado actual de refrigeración (from ACK) ----
                boolean cooling = coolingOn.get();

                // ---- Calcular T[k+1] con modelo térmico ----
                double dT = Q_REAC
                          - (cooling ? Q_COOL : 0.0)
                          - K_LOSS * (currentTemp - T_AMB);
                currentTemp = currentTemp + dtSeconds * dT;

                // ---- Timestamp de generación ----
                long tg = Instant.now().toEpochMilli();

                // ---- Construir payload JSON ----
                // Formato compatible con el esquema de timestamps existente:
                //   id, seq, tg, val, lat_ms + cooling_on para trazabilidad
                String payload = "{ \"id\": \"" + jsonEscape(sensorId) + "\""
                        + ", \"seq\": " + seq
                        + ", \"tg\": " + tg
                        + ", \"val\": " + String.format("%.4f", currentTemp)
                        + ", \"cooling_on\": " + cooling
                        + ", \"lat_ms\": " + latMs
                        + " }";

                // ---- Publicar ----
                MqttClient pubClient = gestorconexiones.getClientByTopicName(mqttTopicName);
                if (pubClient == null && Lclient != null && !Lclient.isEmpty()) {
                    pubClient = Lclient.get(0);
                }

                if (!publisher.Publish(payload, sensorId, mqttTopicName, pubClient)) {
                    if (pubClient != null) gestorconexiones.reconnectClient(pubClient);
                }

                seq++;
            }

            System.out.println("CLOSED_LOOP_SENSOR | finished | sensor_id=" + sensorId);
        }
    }

    public static void main(String[] args) {

        final String mqttTopicName  = getenvOrDefault("MQTT_TOPIC", "C");

        final String mqttBrokerUri  = getenvOrDefault("MQTT_BROKER_URI",
            "tcp://mosquitto-foga0:1883");

        final String clientIdPrefix = getenvOrDefault("MQTT_CLIENT_ID_PREFIX", "ClosedLoopSensor");
        final int publishCount      = getenvIntOrDefault("PUBLISH_COUNT", 99999);
        final int publishIntervalMs = getenvIntOrDefault("PUBLISH_INTERVAL_MS",
            (int)(1000 / 1.0));

        final long intervalMs = Math.max(1L, (long) publishIntervalMs);

        System.out.println("=== CLOSED LOOP SENSOR - Reactor Batch Exotérmico ===");
        System.out.println("MQTT_BROKER_URI="       + mqttBrokerUri);
        System.out.println("MQTT_TOPIC="            + mqttTopicName);
        System.out.println("MQTT_CLIENT_ID_PREFIX=" + clientIdPrefix);
        System.out.println("PUBLISH_COUNT="         + publishCount);
        System.out.println("PUBLISH_INTERVAL_MS="   + publishIntervalMs);
        System.out.println("MODEL: T_init=" + T_INIT + " Q_reac=" + Q_REAC
                + " Q_cool=" + Q_COOL + " k_loss=" + K_LOSS + " T_amb=" + T_AMB);

        int randId = ThreadLocalRandom.current().nextInt(0, 9999999);
        String sensorId = clientIdPrefix + "_" + randId;

        // Un solo hilo: un reactor = un lazo cerrado
        Thread sensorThread = new Thread(
            new SensorThread(mqttBrokerUri, mqttTopicName, sensorId, publishCount, intervalMs),
            "closed-loop-sensor-thread"
        );
        sensorThread.start();

        try {
            sensorThread.join();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        System.out.println("CLOSED_LOOP_SENSOR | main finished");
    }
}
