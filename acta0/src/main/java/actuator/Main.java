
package actuator;

import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.List;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.concurrent.ThreadLocalRandom;

public class Main {

	public static String getIpOfHost(String hostname, int format){
		BufferedReader reader;
		String ip="";
		boolean encontrado=false;
		int port=0;
		try {
			reader = new BufferedReader(new BufferedReader(new InputStreamReader(
				Main.class.getResourceAsStream("/tabladirecciones"))));

			String line;
			for (int i = 0; !encontrado && ((line = reader.readLine()) != null); i++) {
				if(line.toLowerCase().equals(hostname.toLowerCase())) {
					ip = reader.readLine();
					encontrado = true;
					port = i/2;
				}
			}
		} catch (IOException e) {
			e.printStackTrace();
		}

		if(format == 1) {
			ip = "tcp://" + ip + ":" + String.valueOf(1883 + port);
		} else if(format == 2) {
			ip = ip + ":" + String.valueOf(27017 + port);
		}
		return ip;
	}

	// env helper (Kubernetes-friendly)
	private static String getenvOrDefault(String key, String defaultValue) {
		String v = System.getenv(key);
		return (v == null || v.trim().isEmpty()) ? defaultValue : v.trim();
	}

	public static void main(String[] args) throws UnknownHostException {

		final String mqttBrokerUri =
			getenvOrDefault("MQTT_BROKER_URI", "tcp://mosquitto-foga0:1883");
		final String clientIdPrefix =
			getenvOrDefault("MQTT_CLIENT_ID_PREFIX", "acta_0");

		System.out.println("ACTUATOR_BOOT | MQTT_BROKER_URI=" + mqttBrokerUri);
		System.out.println("ACTUATOR_BOOT | MQTT_CLIENT_ID_PREFIX=" + clientIdPrefix);

		List<Topic> Ltopic = new ArrayList<>();
		Topic topic;

		topic = new Topic(
			"B",
			true,
			false
		);
		Ltopic.add(topic);

		List<Broker> Lbroker = new ArrayList<>();

		Broker broker = new Broker(mqttBrokerUri, Ltopic);
		Lbroker.add(broker);

		int randId = ThreadLocalRandom.current().nextInt(0, 9999999);

		GestorDeConexiones gestorconexiones =
			new GestorDeConexiones(clientIdPrefix + "_" + randId, Lbroker);

		gestorconexiones.Iniciar();

		Receiver receiver = new Receiver(gestorconexiones);
		gestorconexiones.setCallback(receiver);

		System.out.println("ACTUATOR_BOOT | ready"
				+ " | actuator_id=" + gestorconexiones.getIDcliente()
				+ " | ack_topic=actuators/ack");
	}
}
