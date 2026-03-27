package actuator;

import java.util.List;

public class Broker{
	String url;
	List<Topic> Ltopic;
	
	public Broker(String url, List<Topic> ltopic) {
		super();
		this.url = url;
		Ltopic = ltopic;
	}

	public String getUrl() {
		return url;
	}

	public void setUrl(String url) {
		this.url = url;
	}

	public List<Topic> getLtopic() {
		return Ltopic;
	}

	public void setLtopic(List<Topic> ltopic) {
		Ltopic = ltopic;
	}

	
}
