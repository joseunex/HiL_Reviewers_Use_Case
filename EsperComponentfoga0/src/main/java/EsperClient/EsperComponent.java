package EsperClient;

import java.util.List;

import com.espertech.esper.client.Configuration;
import com.espertech.esper.client.EPServiceProvider;
import com.espertech.esper.client.EPServiceProviderManager;

public class EsperComponent {
	private EPServiceProvider epService;
	private EsperEPL esper;
	
	public EsperComponent(List<RuleManager> lTopicRules) {
		Configuration config = new Configuration();
		epService = EPServiceProviderManager.getDefaultProvider(config);
		esper = new EsperEPL(epService, lTopicRules);
		esper.run();
		System.out.println("Esper running...");
	}

	public EPServiceProvider getEpService() {
		return epService;
	}

	public void setEpService(EPServiceProvider epService) {
		this.epService = epService;
	}		
}
