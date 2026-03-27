package EsperClient;

import java.util.ArrayList;
import java.util.List;

import com.espertech.esper.client.EPServiceProvider;
import com.espertech.esper.client.EPStatement;
import EsperClient.MyListener;

public class EsperEPL {
	 EPServiceProvider epService;
	 List<MyListener> lListener;
	 
	 public EsperEPL(EPServiceProvider epService, List<RuleManager> lTopicRules) {
		 this.epService = epService;
		 lListener = new ArrayList<MyListener>();
		 initListeners(lTopicRules);
		 //MyListener listener = new MyListener("Hola", "temperatura");
	 }
	 
	 public void initListeners(List<RuleManager> ltopicRules) {
		 MyListener listener;
		 for (int i = 0; i < ltopicRules.size(); i++) {
			listener = new MyListener(ltopicRules.get(i));
			this.lListener.add(listener);
		}
	 }

	 public void run() {
	  // Creating a Statement
	  //String expression = "select Math.max(2, 3) as mymax, avg(price) from Esper1.OrderEvent.win:time(30 sec)";
		 for (int i = 0; i < this.lListener.size(); i++) {
			 EPStatement statement = epService.getEPAdministrator().createEPL(lListener.get(i).getTrules().getRule());
			 statement.addListener(lListener.get(i));
		}
	  
//	  statement = epService.getEPAdministrator().createEPL("select value from Events.LightEvent where value < 5");
////	  // Adding a Listener
//	  statement.addListener(listener2);
	
	  // Sending events
	//	      OrderEvent event = new OrderEvent("shirt", 74.50);
	//	      epService.getEPRuntime().sendEvent(event);
	}
	 
	 
}
