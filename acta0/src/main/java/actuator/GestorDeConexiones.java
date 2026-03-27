package actuator;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import org.eclipse.paho.client.mqttv3.MqttCallback;
import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttException;

public class GestorDeConexiones {
	private String IDcliente;
	private List<Broker> Lbroker;
	private List<MqttClient> Lclient;

	public GestorDeConexiones(String IDcliente, List<Broker> Lbroker) {
		this.IDcliente = IDcliente;
		this.Lbroker = Lbroker;
		this.Lclient = new ArrayList<MqttClient>();
	}

	public void Iniciar () {
		MqttConnectOptions connOpt = new MqttConnectOptions();

		int keepAliveSec = getenvInt("MQTT_KEEPALIVE_SEC", 90);
		int connTimeoutSec = getenvInt("MQTT_CONN_TIMEOUT_SEC", 10);

		connOpt.setCleanSession(true);
		connOpt.setKeepAliveInterval(keepAliveSec);
		connOpt.setConnectionTimeout(connTimeoutSec);

		enableAutoReconnectIfAvailable(connOpt);

		System.out.println("ACTUATOR_MQTT | init"
				+ " | clientId=" + this.IDcliente
				+ " | brokers=" + Lbroker.size()
				+ " | cleanSession=" + connOpt.isCleanSession()
				+ " | keepAliveSec=" + keepAliveSec
				+ " | connTimeoutSec=" + connTimeoutSec
				+ " | broker0=" + (Lbroker.size() > 0 ? Lbroker.get(0).getUrl() : "NA"));

		for(int i=0; i<Lbroker.size(); i++) {
			while(!connectClient(i, connOpt)) {
				try {
					TimeUnit.SECONDS.sleep(3);
				} catch (InterruptedException e) {
					e.printStackTrace();
				}
			}

			for(int j=0; j<Lbroker.get(i).getLtopic().size(); j++) {
				if(Lbroker.get(i).getLtopic().get(j).isSuscribir()) {
					String tname = Lbroker.get(i).getLtopic().get(j).getNombre();
					try {
						Lclient.get(i).subscribe(tname, 0);
						System.out.println("ACTUATOR_MQTT | subscribed"
								+ " | broker=" + Lbroker.get(i).getUrl()
								+ " | topic=" + tname);
					} catch (MqttException e) {
						System.out.println("ACTUATOR_MQTT | subscribe failed"
								+ " | broker=" + Lbroker.get(i).getUrl()
								+ " | topic=" + tname
								+ " | rc=" + e.getReasonCode()
								+ " | msg=" + e.getMessage());
					}
				}
			}
		}

		Thread tconnhealthmonitor = new Thread(new Runnable() {
		    @Override
		    public void run() {
		        connectionHealthMonitor();
		    }
		});
		tconnhealthmonitor.setDaemon(true);
		tconnhealthmonitor.start();
	}

	public void setCallback(MqttCallback cb) {
		if (cb == null) return;
		for (int i = 0; i < this.Lclient.size(); i++) {
			try {
				this.Lclient.get(i).setCallback(cb);
				System.out.println("ACTUATOR_MQTT | callback set"
						+ " | broker=" + this.Lclient.get(i).getServerURI());
			} catch (Exception e) {
				System.out.println("ACTUATOR_MQTT | callback set failed: " + e.getMessage());
			}
		}
	}

	public String getIDcliente() {
		return IDcliente;
	}

	public List<Broker> getLbroker() {
		return Lbroker;
	}

	public List<MqttClient> getLclient() {
		return Lclient;
	}

	public MqttClient getClientByTopicName(String topicName) {
		MqttClient client = null;
		boolean find=false;

		for(int i=0; i<Lbroker.size() && !find; i++) {
			for(int j=0; j<Lbroker.get(i).getLtopic().size() && !find; j++) {
				if(Lbroker.get(i).getLtopic().get(j).getNombre().equals(topicName)) {
					for(int k=0; k<Lclient.size() && !find; k++) {
						if(Lclient.get(k).getServerURI().equals(Lbroker.get(i).getUrl())) {
							find=true;
							client = Lclient.get(k);
						}
					}
				}
			}
		}

		return client;
	}

	public Broker getBrokerByURI(String brokerURI) {
		boolean find = false;
		Broker broker = null;
		for(int i=0; i<Lbroker.size() && !find; i++) {
			if(Lbroker.get(i).getUrl() != null && Lbroker.get(i).getUrl().equals(brokerURI)) {
				find = true;
				broker = Lbroker.get(i);
			}
		}
		return broker;
	}

	public boolean connectClient(int clientIndex, MqttConnectOptions connOpt) {
		boolean connected = false;

		try {
			String brokerUrl = Lbroker.get(clientIndex).getUrl();
			System.out.println("ACTUATOR_MQTT | connecting..."
					+ " | broker=" + brokerUrl
					+ " | clientId=" + this.IDcliente);

			MqttClient myClient = new MqttClient(brokerUrl, this.IDcliente);
			myClient.connect(connOpt);

			Lclient.add(myClient);

			System.out.println("ACTUATOR_MQTT | connected"
					+ " | broker=" + brokerUrl
					+ " | clientId=" + this.IDcliente);

			connected = true;

		} catch (MqttException e) {
			System.out.println("ACTUATOR_MQTT | connect failed"
					+ " | broker=" + Lbroker.get(clientIndex).getUrl()
					+ " | rc=" + e.getReasonCode()
					+ " | msg=" + e.getMessage()
					+ " | retry in 3s");
		} catch (Exception e) {
			System.out.println("ACTUATOR_MQTT | connect failed (unexpected): " + e.getMessage());
		}

		return connected;
	}

	public void reconnectClient(MqttClient myClient) {
		if (myClient == null || myClient.isConnected()) return;

		System.out.println("ACTUATOR_MQTT | reconnecting..."
				+ " | broker=" + safeUri(myClient)
				+ " | clientId=" + this.IDcliente);

		// FIX: usar connect() síncrono en lugar de reconnect() asíncrono.
		// Con cleanSession=true, reconnect() retorna antes de que la conexión
		// se complete, por lo que isConnected() devuelve false inmediatamente
		// después y las reuscripciones nunca se ejecutan.
		MqttConnectOptions opts = new MqttConnectOptions();
		opts.setCleanSession(true);
		opts.setKeepAliveInterval(getenvInt("MQTT_KEEPALIVE_SEC", 90));
		opts.setConnectionTimeout(getenvInt("MQTT_CONN_TIMEOUT_SEC", 10));

		try {
			myClient.connect(opts);
		} catch (MqttException e) {
			System.out.println("ACTUATOR_MQTT | reconnect failed"
					+ " | broker=" + safeUri(myClient)
					+ " | rc=" + e.getReasonCode()
					+ " | msg=" + e.getMessage());
			return;
		} catch (Exception e) {
			System.out.println("ACTUATOR_MQTT | reconnect failed (unexpected)"
					+ " | broker=" + safeUri(myClient)
					+ " | msg=" + e.getMessage());
			return;
		}

		// Ahora isConnected() es fiable porque connect() es síncrono
		if (myClient.isConnected()) {
			System.out.println("ACTUATOR_MQTT | reconnected"
					+ " | broker=" + myClient.getServerURI());

			Broker broker = getBrokerByURI(myClient.getServerURI());
			if (broker == null) {
				System.out.println("ACTUATOR_MQTT | WARNING: broker not found for URI="
						+ myClient.getServerURI() + " (cannot resubscribe)");
				return;
			}

			System.out.println("ACTUATOR_MQTT | resubscribing"
					+ " | broker=" + broker.getUrl()
					+ " | topics=" + broker.getLtopic().size());

			for(int i=0; i < broker.getLtopic().size(); i++) {
				if(broker.getLtopic().get(i).isSuscribir()) {
					String tname = broker.getLtopic().get(i).getNombre();
					try {
						myClient.subscribe(tname, 0);
						System.out.println("ACTUATOR_MQTT | resubscribed topic=" + tname);
					} catch (MqttException e) {
						System.out.println("ACTUATOR_MQTT | resubscribe failed"
								+ " | topic=" + tname
								+ " | rc=" + e.getReasonCode()
								+ " | msg=" + e.getMessage());
					}
				}
			}
		}
	}

	public void connectionHealthMonitor() {
		while (true) {
			for (int i = 0; i < this.Lclient.size(); i++) {
				reconnectClient(this.Lclient.get(i));
			}
			try {
				TimeUnit.SECONDS.sleep(3);
			} catch (InterruptedException e) {
				e.printStackTrace();
			}
		}
	}

	// ---------- helpers ----------

	private static int getenvInt(String key, int def) {
		try {
			String v = System.getenv(key);
			if (v == null || v.trim().isEmpty()) return def;
			return Integer.parseInt(v.trim());
		} catch (Exception e) {
			return def;
		}
	}

	private static void enableAutoReconnectIfAvailable(MqttConnectOptions connOpt) {
		try {
			connOpt.getClass()
				.getMethod("setAutomaticReconnect", boolean.class)
				.invoke(connOpt, true);
			System.out.println("ACTUATOR_MQTT | automaticReconnect=true (enabled)");
		} catch (Exception e) {
			System.out.println("ACTUATOR_MQTT | automaticReconnect not available (ignored)");
		}
	}

	private static String safeUri(MqttClient c) {
		try {
			return (c == null) ? "null" : c.getServerURI();
		} catch (Exception e) {
			return "unknown";
		}
	}
}
