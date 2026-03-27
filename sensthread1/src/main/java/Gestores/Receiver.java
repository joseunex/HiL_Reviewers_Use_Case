package Gestores;

import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttCallback;
import org.eclipse.paho.client.mqttv3.MqttMessage;

public class Receiver implements MqttCallback{
	Publisher pub;
	GestorDeConexiones gestorconexiones;
	
	public Receiver(GestorDeConexiones gestorconexiones, Publisher pub) {
		this.gestorconexiones = gestorconexiones;
		this.pub = pub;
		for( int i=0; i<this.gestorconexiones.getLclient().size(); i++) {
			this.gestorconexiones.getLclient().get(i).setCallback(this);
		}
	}

	public void connectionLost(Throwable cause) {
		// TODO Auto-generated method stub
		
	}

	public void messageArrived(String topic, MqttMessage message) throws Exception {
		String dataReceived = new String(message.getPayload());
		System.out.println("DEVICE " +this.gestorconexiones.getIDcliente()+ " | Mensaje recibido: " + dataReceived + "| From topic: "+ topic);

//		if(dataReceived.equals("hola"))
//			pub.Publish("recibido!", topic, gestorconexiones.getClientByTopicName(topic));
	}

	public void deliveryComplete(IMqttDeliveryToken token) {
		// TODO Auto-generated method stub
		
	}

}
