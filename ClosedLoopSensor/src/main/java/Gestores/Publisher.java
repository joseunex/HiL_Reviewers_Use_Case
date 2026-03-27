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
        System.out.println("CLOSED_LOOP_SENSOR " + myId + " | Publishing data = " + pubMessage + " | To topic " + myTopic);
        MqttDeliveryToken token = null;
        try {
            token = myTopic.publish(message);
            token.waitForCompletion();
            published = true;
        } catch (Exception e) {
            System.out.println("PROBLEMs publishing to " + myClient.getServerURI() + ", attempting to reconnect");
        }
        return published;
    }
}
