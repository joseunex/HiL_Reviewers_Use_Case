package Gestores;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;
import org.eclipse.paho.client.mqttv3.MqttClient;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.time.Instant;

public class Main {

	public static List<String> LoadCsv(int messagesAmount, String csvName){
		BufferedReader reader;
		List<String> ldata = new ArrayList<>();
		try {
			reader = new BufferedReader(new BufferedReader(new InputStreamReader(
				Main.class.getResourceAsStream("/" + csvName + ".csv")
			)));
			String line;
			for (int i = 0; ((line = reader.readLine()) != null) && i < messagesAmount; i++) {
				ldata.add(line);
			}
		} catch (IOException e) {
			e.printStackTrace();
		}
		return ldata;
	}

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

	private static String csvToJsonValue(String raw) {
		if (raw == null) return "\"\"";
		String v = raw.trim();
		if (v.isEmpty()) return "\"\"";
		try { Long.parseLong(v);   return v; } catch (NumberFormatException ignore) {}
		try { Double.parseDouble(v); return v; } catch (NumberFormatException ignore) {}
		return "\"" + jsonEscape(v) + "\"";
	}

	// ---- sensor thread ----
	static class SensorThread implements Runnable {
		private final String mqttBrokerUri;
		private final String mqttTopicName;
		private final String clientIdPrefix;
		private final int    publishCount;
		private final long   intervalMs;
		private final List<String> ldata;

		SensorThread(String mqttBrokerUri, String mqttTopicName, String clientIdPrefix,
				int publishCount, long intervalMs, List<String> ldata) {
			this.mqttBrokerUri  = mqttBrokerUri;
			this.mqttTopicName  = mqttTopicName;
			this.clientIdPrefix = clientIdPrefix;
			this.publishCount   = publishCount;
			this.intervalMs     = intervalMs;
			this.ldata          = ldata;
		}

		@Override
		public void run() {
			// Each thread is an independent sensor instance with its own connection
			int randId = ThreadLocalRandom.current().nextInt(0, 9999999);
			String sensorId = clientIdPrefix + "_" + randId;

			List<Topic> Ltopic = new ArrayList<Topic>();
			Topic topic;
			topic = new Topic("C",
				false,
				true);
			Ltopic.add(topic);

			List<Broker> Lbroker = new ArrayList<Broker>();
			Lbroker.add(new Broker(mqttBrokerUri, Ltopic));

			GestorDeConexiones gestorconexiones = new GestorDeConexiones(sensorId, Lbroker);
			gestorconexiones.Iniciar();
			Publisher publisher = new Publisher();
			new Receiver(gestorconexiones, publisher);

			List<MqttClient> Lclient = gestorconexiones.getLclient();

			System.out.println("SENSOR_THREAD | started"
					+ " | sensor_id=" + sensorId
					+ " | broker=" + mqttBrokerUri
					+ " | topic=" + mqttTopicName
					+ " | publish_count=" + publishCount
					+ " | interval_ms=" + intervalMs);

			long nextPublishMs = (System.nanoTime() / 1_000_000L) + intervalMs;
			long seq = 0L;

			for (int i = 0; i < publishCount; i++) {

				long nowMs = System.nanoTime() / 1_000_000L;
				long sleepMs = nextPublishMs - nowMs;
				if (sleepMs > 0) {
					try { Thread.sleep(sleepMs); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
				}

				long actualMs = System.nanoTime() / 1_000_000L;
				long latMs = Math.max(0L, actualMs - nextPublishMs);
				nextPublishMs += intervalMs;

				long tg = Instant.now().toEpochMilli();
				final long seqNow = seq;

				MqttClient pubClient = gestorconexiones.getClientByTopicName(mqttTopicName);
				if (pubClient == null && Lclient != null && !Lclient.isEmpty()) pubClient = Lclient.get(0);

				String payload;
				int val = ThreadLocalRandom.current().nextInt(
					79,
					88 + 1
				);
				payload = "{ \"id\": \"" + jsonEscape(sensorId) + "\", \"seq\": " + seqNow + ", \"tg\": " + tg + ", \"val\": " + val + ", \"lat_ms\": " + latMs + " }";

				if (!publisher.Publish(payload, gestorconexiones.getIDcliente(), mqttTopicName, pubClient)) {
					if (pubClient != null) gestorconexiones.reconnectClient(pubClient);
				}

				seq++;
			}

			System.out.println("SENSOR_THREAD | finished | sensor_id=" + sensorId);
		}
	}

	public static void main(String[] args) {

		final String mqttTopicName  = getenvOrDefault("MQTT_TOPIC",
			"C");
		final String mqttBrokerUri  = getenvOrDefault("MQTT_BROKER_URI",
			"tcp://mosquitto-foga0:1883");
		final String clientIdPrefix = getenvOrDefault("MQTT_CLIENT_ID_PREFIX", "sensthread1");
		final int publishCount      = getenvIntOrDefault("PUBLISH_COUNT", 99999);
		final int publishIntervalMs = getenvIntOrDefault("PUBLISH_INTERVAL_MS",
			(int)(1000/(1.0*1.0)));

		// quantity: number of parallel sensor threads
		// overridable via env, default comes from model attribute
		final int quantity = getenvIntOrDefault("SENSOR_QUANTITY",
			100);

		final long intervalMs = Math.max(1L, (long) publishIntervalMs);

		System.out.println("MQTT_BROKER_URI="      + mqttBrokerUri);
		System.out.println("MQTT_TOPIC="           + mqttTopicName);
		System.out.println("MQTT_CLIENT_ID_PREFIX="+ clientIdPrefix);
		System.out.println("PUBLISH_COUNT="        + publishCount);
		System.out.println("PUBLISH_INTERVAL_MS="  + publishIntervalMs);
		System.out.println("SENSOR_QUANTITY="      + quantity);

		List<String> ldata = new ArrayList<>();

		List<Thread> threads = new ArrayList<Thread>();
		for (int t = 0; t < quantity; t++) {
			Thread thread = new Thread(
				new SensorThread(mqttBrokerUri, mqttTopicName, clientIdPrefix, publishCount, intervalMs, ldata),
				"sensor-thread-" + t
			);
			threads.add(thread);
			thread.start();
			System.out.println("SENSOR_MAIN | launched thread " + t + " of " + quantity);
		}

		// Wait for all threads to finish
		for (Thread thread : threads) {
			try {
				thread.join();
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
			}
		}

		System.out.println("SENSOR_MAIN | all " + quantity + " threads finished");
	}
}
