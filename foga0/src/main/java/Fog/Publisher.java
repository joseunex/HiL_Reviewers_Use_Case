package Fog;

import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.MqttTopic;

public class Publisher {
	
	public void Publish(String pubMessage, String topic, MqttClient myClient) {
		MqttTopic myTopic = myClient.getTopic(topic);
		int pubQoS = 0;
		MqttMessage message = new MqttMessage(pubMessage.getBytes());
		message.setQos(pubQoS);
		message.setRetained(false);
		// Publish the message
		System.out.println("FOG | Publishing data: " + pubMessage + " | To topic: " + myTopic );		MqttDeliveryToken token = null;
		try {
			// publish message to broker
			token = myTopic.publish(message);
	    	// Wait until the message has been delivered to the broker
			// B2: bounded wait on the delivery token instead of the former fixed Thread.sleep(100)
			//     (same change as in the CEP publisher; this path is only used for inter-Fog routing)
			token.waitForCompletion(1000L);
		} catch (Exception e) {
			e.printStackTrace();
		}
	}
}
