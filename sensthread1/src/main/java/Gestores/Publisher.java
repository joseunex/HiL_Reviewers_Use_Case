package Gestores;

import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.MqttTopic;

public class Publisher {
	
	public boolean Publish(String pubMessage, String myId, String topic, MqttClient myClient) {
		boolean published = false;
		MqttTopic myTopic = myClient.getTopic(topic);
		int pubQoS = 0;
		MqttMessage message = new MqttMessage(pubMessage.getBytes());
		message.setQos(pubQoS);
		message.setRetained(false);
		// Publish the message
		System.out.println("DEVICE " + myId + " | Publishing data = " + pubMessage + " | To topic " + myTopic);
		MqttDeliveryToken token = null;
		try {
			// publish message to broker
			token = myTopic.publish(message);
	    	// Wait until the message has been delivered to the broker
			token.waitForCompletion();
			published = true;
			//Thread.sleep(100);
		} catch (Exception e) {
			//e.printStackTrace();
			System.out.println("PROBLEMs publishing to " + myClient.getServerURI() + ", attempting to reconnect");
		}
		return published;
	}
}
