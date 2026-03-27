package actuator;

import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttCallback;
import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttException;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.json.JSONObject;

public class Receiver implements MqttCallback {
	private final GestorDeConexiones gestorconexiones;

	private static final String ACK_TOPIC = "actuators/ack";
	private static final int ACK_QOS = 0;

	private final LinkedBlockingQueue<String> ackQueue;
	private final int ackQueueCapacity;

	public Receiver(GestorDeConexiones gestorconexiones) {
		this.gestorconexiones = gestorconexiones;

		this.ackQueueCapacity = getenvInt("ACK_QUEUE_CAPACITY", 5000);
		this.ackQueue = new LinkedBlockingQueue<String>(this.ackQueueCapacity);

		System.out.println("ACTUATOR_RECEIVER | init"
				+ " | actuator_id=" + this.gestorconexiones.getIDcliente()
				+ " | ack_topic=" + ACK_TOPIC
				+ " | ack_qos=" + ACK_QOS
				+ " | ack_queue_capacity=" + this.ackQueueCapacity);

		startAckPublisherThread();
	}

	@Override
	public void connectionLost(Throwable cause) {
		System.out.println("ACTUATOR_MQTT | connectionLost"
				+ " | actuator_id=" + this.gestorconexiones.getIDcliente()
				+ " | cause=" + (cause != null ? cause.getMessage() : "null"));
	}

	@Override
	public void messageArrived(String topic, MqttMessage message) throws Exception {

		final long t_cmd_rcv_act = System.currentTimeMillis();

		final String dataReceived = new String(message.getPayload(), StandardCharsets.UTF_8);

		// --- sensor fields ---
		String idSensor   = "";
		long   seq        = -1L;
		long   tg         = -1L;
		Object valObj     = null;

		// --- cep fields ---
		long tsrEsper = -1L;
		long tsnEsper = -1L;
		JSONObject cepDrops = null;

		// --- command fields ---
		String cmdId        = "";
		String desiredState = "";

		boolean parsedOk = false;

		try {
			JSONObject json = new JSONObject(dataReceived);

			// sensor
			idSensor = json.optString("id", "");
			seq      = json.optLong("seq", -1L);
			tg       = json.optLong("tg", -1L);
			if (tg < 0) tg = json.optLong("ts", -1L);
			valObj   = json.opt("val");

			// cep
			tsrEsper = json.optLong("tsr_esper", -1L);
			tsnEsper = json.optLong("tsn_esper", -1L);

			// cep drop counters (passthrough from CEP notification)
			if (json.has("cep_drops")) {
				cepDrops = json.getJSONObject("cep_drops");
			}

			// command
			cmdId = json.optString("cmd_id", "");
			if (cmdId == null || cmdId.trim().isEmpty()) {
				cmdId = (idSensor != null && !idSensor.trim().isEmpty())
						? idSensor
						: UUID.randomUUID().toString();
			}

			desiredState = json.optString("desired_state", "");
			if (desiredState == null || desiredState.trim().isEmpty()) {
				desiredState = json.optString("msg", "");
			}

			parsedOk = true;

		} catch (Exception e) {
			parsedOk = false;
			cmdId = UUID.randomUUID().toString();
			System.out.println("ACTUATOR_CMD | parse failed"
					+ " | actuator_id=" + this.gestorconexiones.getIDcliente()
					+ " | topic=" + topic
					+ " | err=" + e.getMessage()
					+ " | raw=" + dataReceived);
		}

		final String appliedState    = desiredState;
		final long   t_act_act       = System.currentTimeMillis();
		final long   t_ack_pub_act   = System.currentTimeMillis();

		// ---------- build ACK ----------

		JSONObject ack = new JSONObject();
		ack.put("type",      "actuator_ack");
		ack.put("cmd_id",    cmdId);
		ack.put("parsed_ok", parsedOk);

		// -- sensor block --
		JSONObject sensorBlock = new JSONObject();
		if (idSensor != null && !idSensor.isEmpty()) sensorBlock.put("id",  idSensor);
		if (seq    >= 0) sensorBlock.put("seq", seq);
		if (tg     >= 0) sensorBlock.put("tg",  tg);
		if (valObj != null)                        sensorBlock.put("val", valObj);
		ack.put("sensor", sensorBlock);

		// -- cep block --
		JSONObject cepBlock = new JSONObject();
		if (tsrEsper >= 0) cepBlock.put("tsr_esper", tsrEsper);
		if (tsnEsper >= 0) cepBlock.put("tsn_esper", tsnEsper);
		if (cepDrops != null) cepBlock.put("cep_drops", cepDrops);
		ack.put("cep", cepBlock);

		// -- actuator block --
		JSONObject actuatorBlock = new JSONObject();
		actuatorBlock.put("id",            this.gestorconexiones.getIDcliente());
		actuatorBlock.put("cmd_topic",     topic);
		actuatorBlock.put("ack_topic",     ACK_TOPIC);
		actuatorBlock.put("desired_state", desiredState);
		actuatorBlock.put("applied_state", appliedState);
		actuatorBlock.put("t_cmd_rcv_act", t_cmd_rcv_act);
		actuatorBlock.put("t_act_act",     t_act_act);
		actuatorBlock.put("t_ack_pub_act", t_ack_pub_act);
		ack.put("actuator", actuatorBlock);

		// ---------- enqueue ----------
		boolean enqueued = this.ackQueue.offer(ack.toString());
		if (!enqueued) {
			System.out.println("ACTUATOR_ACK | DROP (queue full)"
					+ " | actuator_id=" + this.gestorconexiones.getIDcliente()
					+ " | queue_size=" + this.ackQueue.size()
					+ " | queue_capacity=" + this.ackQueueCapacity);
		}

		System.out.println("ACTUATOR | actuator_id=" + this.gestorconexiones.getIDcliente()
				+ " | cmd_topic="    + topic
				+ " | cmd_id="       + cmdId
				+ " | desired="      + desiredState
				+ " | applied="      + appliedState
				+ " | ack_topic="    + ACK_TOPIC
				+ " | parsed_ok="    + parsedOk
				+ " | ack_enqueued=" + enqueued);
	}

	@Override
	public void deliveryComplete(IMqttDeliveryToken token) { }

	// ---------- ACK publisher thread ----------

	private void startAckPublisherThread() {
		Thread t = new Thread(new Runnable() {
			@Override
			public void run() {
				ackPublisherLoop();
			}
		});
		t.setDaemon(true);
		t.setName("actuator-ack-publisher");
		t.start();
		System.out.println("ACTUATOR_ACK | publisher thread started");
	}

	private void ackPublisherLoop() {
		while (true) {
			try {
				String ackJson = ackQueue.poll(2, TimeUnit.SECONDS);
				if (ackJson == null) continue;

				MqttClient c = pickClient();
				if (c == null) {
					System.out.println("ACTUATOR_ACK | no MQTT client available"
							+ " | actuator_id=" + gestorconexiones.getIDcliente()
							+ " | queue_size=" + ackQueue.size());
					ackQueue.offer(ackJson);
					TimeUnit.SECONDS.sleep(1);
					continue;
				}

				boolean connected = false;
				try { connected = c.isConnected(); } catch (Exception ignore) { }

				if (!connected) {
					System.out.println("ACTUATOR_ACK | client disconnected (will retry)"
							+ " | actuator_id=" + gestorconexiones.getIDcliente()
							+ " | broker=" + safeUri(c)
							+ " | queue_size=" + ackQueue.size());
					ackQueue.offer(ackJson);
					TimeUnit.SECONDS.sleep(1);
					continue;
				}

				try {
					MqttMessage m = new MqttMessage(ackJson.getBytes(StandardCharsets.UTF_8));
					m.setQos(ACK_QOS);
					c.publish(ACK_TOPIC, m);

					System.out.println("ACTUATOR_ACK | published"
							+ " | actuator_id=" + gestorconexiones.getIDcliente()
							+ " | broker=" + safeUri(c)
							+ " | queue_size=" + ackQueue.size());

				} catch (MqttException e) {
					System.out.println("ACTUATOR_ACK | publish failed"
							+ " | actuator_id=" + gestorconexiones.getIDcliente()
							+ " | broker=" + safeUri(c)
							+ " | rc=" + e.getReasonCode()
							+ " | msg=" + e.getMessage()
							+ " | queue_size=" + ackQueue.size());
					ackQueue.offer(ackJson);
					TimeUnit.MILLISECONDS.sleep(500);
				}

			} catch (Exception e) {
				System.out.println("ACTUATOR_ACK | publisher loop error: " + e.getMessage());
			}
		}
	}

	private MqttClient pickClient() {
		for (int i = 0; i < gestorconexiones.getLclient().size(); i++) {
			MqttClient tmp = gestorconexiones.getLclient().get(i);
			try {
				if (tmp != null && tmp.isConnected()) return tmp;
			} catch (Exception ignore) { }
		}
		if (gestorconexiones.getLclient().size() > 0) {
			return gestorconexiones.getLclient().get(0);
		}
		return null;
	}

	private static String safeUri(MqttClient c) {
		try {
			return (c == null) ? "null" : c.getServerURI();
		} catch (Exception e) {
			return "unknown";
		}
	}

	private static int getenvInt(String key, int def) {
		try {
			String v = System.getenv(key);
			if (v == null || v.trim().isEmpty()) return def;
			return Integer.parseInt(v.trim());
		} catch (Exception e) {
			return def;
		}
	}
}
