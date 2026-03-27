package EsperClient;

import java.util.List;

import org.eclipse.paho.client.mqttv3.MqttClient;

public class RuleManager {
	String Rule;
	String message;
	List<String> lInputTopic;
	List<String> lOutputTopic;
	MqttClient client;
	
	public RuleManager(String Rule, String message, MqttClient client, List<String> lInputTopic, List<String> lOutputTopic) {
		this.Rule = Rule;
		this.message = message;
		this.lInputTopic = lInputTopic;
		this.lOutputTopic = lOutputTopic;
		this.client = client;
	}

	public String getRule() {
		return Rule;
	}

	public void setRule(String rule) {
		Rule = rule;
	}

	public List<String> getlInputTopic() {
		return lInputTopic;
	}

	public void setlInputTopic(List<String> lInputTopic) {
		this.lInputTopic = lInputTopic;
	}

	public List<String> getlOutputTopic() {
		return lOutputTopic;
	}

	public void setlOutputTopic(List<String> lOutputTopic) {
		this.lOutputTopic = lOutputTopic;
	}

	public MqttClient getClient() {
		return client;
	}

	public void setClient(MqttClient client) {
		this.client = client;
	}

	public String getMessage() {
		return message;
	}

	public void setMessage(String message) {
		this.message = message;
	}
		
}
