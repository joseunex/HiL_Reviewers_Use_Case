package EsperClient;

import java.util.concurrent.atomic.AtomicLong;

import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.MqttTopic;

public class Publisher {

	// B2: bounded wait for the delivery token. With QoS 0 the token completes as soon as the
	// message has been handed to the network layer (well below 1 ms in a local network).
	private static final long PUB_TIMEOUT_MS = 1000L;

	// B2: publication statistics, reported periodically by Receiver (ESPER_STATS lines)
	static final AtomicLong published    = new AtomicLong(0);
	static final AtomicLong failed       = new AtomicLong(0);
	static final AtomicLong blockedUsSum = new AtomicLong(0);
	static final AtomicLong blockedUsMax = new AtomicLong(0);

	public void Publish(String pubMessage, String topic, MqttClient myClient) {
	//	System.out.println("Publicando..");
		MqttTopic myTopic = myClient.getTopic(topic);
		int pubQoS = 0;
		MqttMessage message = new MqttMessage(pubMessage.getBytes());
		message.setQos(pubQoS);
		message.setRetained(false);
		// Publish the message
		System.out.println("ESPER | Publishing data: " + pubMessage + " | To topic: " + myTopic );
		MqttDeliveryToken token = null;
		long t0 = System.nanoTime(); // B2
		try {
			// publish message to broker
			token = myTopic.publish(message);
			// Wait until the message has been delivered to the broker
			// B2: wait on the delivery token instead of the former fixed Thread.sleep(100), which
			//     blocked the thread that releases events to Esper and capped the CEP output at
			//     about 10 notifications per second
			token.waitForCompletion(PUB_TIMEOUT_MS);
			published.incrementAndGet();
		} catch (Exception e) {
			failed.incrementAndGet();
			e.printStackTrace();
		} finally {
			long us = (System.nanoTime() - t0) / 1000L;
			blockedUsSum.addAndGet(us);
			blockedUsMax.accumulateAndGet(us, Math::max);
		}
	}
}
