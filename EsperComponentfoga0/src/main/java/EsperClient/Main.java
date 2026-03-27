package EsperClient;

import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.List;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;

public class Main {

	public static String getIpOfHost(String hostname, int format){
		BufferedReader reader;
		String ip="";
		boolean encontrado=false;
		int port=0;
		try {
			reader = new BufferedReader(new BufferedReader(new InputStreamReader(Main.class.getResourceAsStream("/tabladirecciones"))));

			String line;
			for (int i = 0; !encontrado && ((line = reader.readLine()) != null); i++)
			{
				if(line.toLowerCase().equals(hostname.toLowerCase())) {
					ip=reader.readLine();
					encontrado=true;
					port = i/2;
				}
			}
		} catch (IOException e) {
			e.printStackTrace();
		}

		if(format==1) {
			ip = "tcp://"+ip+":"+String.valueOf(1883+port);
		}else {
			if(format==2) {
				ip = ip+":"+String.valueOf(27017+port);
			}
		}

		return ip;
	}

	// NEW: env helper
	private static String getenvOrDefault(String key, String defaultValue) { // NEW
		String v = System.getenv(key); // NEW
		return (v == null || v.trim().isEmpty()) ? defaultValue : v.trim(); // NEW
	} // NEW

	public static void main(String[] args) throws UnknownHostException {

		// NEW: Kubernetes-friendly runtime config
		final String mqttBrokerUri = getenvOrDefault("MQTT_BROKER_URI", "tcp://mosquitto-foga0:1883"); // NEW
		final String cepClientId  = getenvOrDefault("CEP_CLIENT_ID", "foga_EsperComponent"); // NEW

		// NEW: Log effective config
		System.out.println("MQTT_BROKER_URI=" + mqttBrokerUri); // NEW
		System.out.println("CEP_CLIENT_ID=" + cepClientId); // NEW

		List<Topic> Ltopic = new ArrayList<Topic>();
		Topic topic;
		topic = new Topic("Z",
			true,
			false
		);
		Ltopic.add(topic);
		topic = new Topic("C",
			true,
			false
		);
		Ltopic.add(topic);
		topic = new Topic("B",
			false,
			true
		);
		Ltopic.add(topic);
		topic = new Topic("D",
			false,
			true
		);
		Ltopic.add(topic);

		List<Broker> Lbroker = new ArrayList<Broker>();

		// CHANGED: remove port offsets (1883+i). Use env-configured broker URI.
		Broker broker = new Broker(mqttBrokerUri, Ltopic); // CHANGED
		Lbroker.add(broker);

		// CHANGED: client id configurable by env
		GestorDeConexiones gestorconexiones = new GestorDeConexiones(cepClientId, Lbroker); // CHANGED
		gestorconexiones.Iniciar();
		Publisher publisher = new Publisher();

		List<RuleManager> lTopicRules = new ArrayList<RuleManager>();
		List<String> inputTopics  = new ArrayList<String>();
		List<String> outputTopics = new ArrayList<String>();

		inputTopics  = new ArrayList<String>();
		outputTopics = new ArrayList<String>();
		inputTopics.add("Z");
		outputTopics.add("B");

		// Rule stays as-is (no threshold injection).
		lTopicRules.add(new RuleManager("select * from EsperClient.majorthan80 where value > 80.0", "ON", gestorconexiones.getLclient().get(0), inputTopics, outputTopics));
		inputTopics  = new ArrayList<String>();
		outputTopics = new ArrayList<String>();
		inputTopics.add("Z");
		outputTopics.add("B");

		// Rule stays as-is (no threshold injection).
		lTopicRules.add(new RuleManager("select * from EsperClient.minorthan79 where value < 79.0", "OFF", gestorconexiones.getLclient().get(0), inputTopics, outputTopics));
		inputTopics  = new ArrayList<String>();
		outputTopics = new ArrayList<String>();
		inputTopics.add("C");
		outputTopics.add("D");

		// Rule stays as-is (no threshold injection).
		lTopicRules.add(new RuleManager("select * from EsperClient.majorthan80othersensors where value > 87.0", "ON", gestorconexiones.getLclient().get(0), inputTopics, outputTopics));
		inputTopics  = new ArrayList<String>();
		outputTopics = new ArrayList<String>();
		inputTopics.add("C");
		outputTopics.add("D");

		// Rule stays as-is (no threshold injection).
		lTopicRules.add(new RuleManager("select * from EsperClient.minorthan79othersensors where value < 80.0", "OFF", gestorconexiones.getLclient().get(0), inputTopics, outputTopics));

		EsperComponent esp = new EsperComponent(lTopicRules);
		Receiver receiver = new Receiver(gestorconexiones, publisher, esp);
	}
}
