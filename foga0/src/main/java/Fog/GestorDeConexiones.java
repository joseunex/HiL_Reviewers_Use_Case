package Fog;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.TimeUnit;

import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions; 
import org.eclipse.paho.client.mqttv3.MqttException;
import org.eclipse.paho.client.mqttv3.MqttSecurityException;

public class GestorDeConexiones {
	private String IDcliente;
	private List<Broker> Lbroker;
	private List<MqttClient> Lclient;
	
	public GestorDeConexiones(String IDcliente, List<Broker> Lbroker) {
		this.IDcliente = IDcliente;
		this.Lbroker = Lbroker;
		Lclient = new ArrayList<MqttClient>();
	}
	
	public void Iniciar (){
		MqttClient myClient = null;
		MqttConnectOptions connOpt;
		
		connOpt = new MqttConnectOptions();
		connOpt.setCleanSession(true);
		connOpt.setKeepAliveInterval(30);

		for(int i=0; i<Lbroker.size(); i++) {
			while(!connectClient(i, connOpt)) {
				try {
					TimeUnit.SECONDS.sleep(3);
				} catch (InterruptedException e) {
					// TODO Auto-generated catch block
					e.printStackTrace();
				}
			}
						
			for(int j=0; j<Lbroker.get(i).getLtopic().size(); j++) {
				if(Lbroker.get(i).getLtopic().get(j).isSuscribir()) {
					try {
						Lclient.get(i).subscribe(Lbroker.get(i).getLtopic().get(j).getNombre(), 0);
					} catch (MqttException e) {
						e.printStackTrace();
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
		tconnhealthmonitor.start();
	}
	
	public String getIDcliente() {
		return IDcliente;
	}

	public void setIDcliente(String iDcliente) {
		IDcliente = iDcliente;
	}

	public List<Broker> getLbroker() {
		return Lbroker;
	}

	public void setLbroker(List<Broker> lbroker) {
		Lbroker = lbroker;
	}

	public List<MqttClient> getLclient() {
		return Lclient;
	}

	public void setLclient(List<MqttClient> lclient) {
		Lclient = lclient;
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
			if(Lbroker.get(i).getUrl() == brokerURI) {
				find = true;
				broker = Lbroker.get(i);
			}
		}
		return broker;
	}
	
	public boolean connectClient(int clientIndex, MqttConnectOptions connOpt) {
		boolean connected = false;
		MqttClient myClient;
		
		try {
			myClient = new MqttClient(Lbroker.get(clientIndex).getUrl(), this.IDcliente);
			myClient.connect(connOpt);
			Lclient.add(myClient);
			System.out.println("Connected to " + Lbroker.get(clientIndex).getUrl());
			connected = true;
		} catch (MqttException e) {
				System.out.println("PROBLEMs connectting to " + Lbroker.get(clientIndex).getUrl() + ", waiting 3 seconds for the next connection attempt");
		}
		return connected;			
	}
	
	public void reconnectClient(MqttClient myClient) {
		
		while (!myClient.isConnected()) {
			try {
				myClient.reconnect();
			} catch (MqttException e) {
				System.out.println("PROBLEMs reconnectting to " + myClient.getServerURI() + ", waiting 3 seconds for the next reconnection attempt");
				try {
					TimeUnit.SECONDS.sleep(3);
				} catch (InterruptedException e2) { 
					e2.printStackTrace();
				}
			}
			
			if(myClient.isConnected()) {
				System.out.println("Client reconnected to: " + myClient.getServerURI());
				System.out.println("Resubscribing to topics...");
				Broker broker = getBrokerByURI(myClient.getServerURI());
				for(int i=0; i < broker.getLtopic().size(); i++) {
					if(broker.getLtopic().get(i).isSuscribir()) {
						try {
							myClient.subscribe(broker.getLtopic().get(i).getNombre(), 0);
						} catch (MqttException e) {
							e.printStackTrace();
						}
					}
				}
			}
		}
	}
	
	// This method is designed as a thread to monitor the connection health and attempt to reconnect if it is lost.
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
	
	
}
