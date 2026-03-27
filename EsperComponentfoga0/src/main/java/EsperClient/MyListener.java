package EsperClient;

import org.json.JSONObject;
import com.espertech.esper.client.EventBean;
import com.espertech.esper.client.UpdateListener;

public class MyListener implements UpdateListener {
  Publisher publisher;
  RuleManager trules;

  public MyListener(RuleManager trules) {
    this.publisher = new Publisher();
    this.trules = trules;
  }

  public void update(EventBean[] newEvents, EventBean[] oldEvents) {
    EventBean eb = newEvents[0];

    // Recupera el evento original (subclase de Event)
    Event ev = (Event) eb.getUnderlying();

    // tsn_esper justo antes de notificar
    long tsnEsper = System.currentTimeMillis();
    ev.setTsnEsper(tsnEsper);

    // Construye payload de notificación con timestamps
    JSONObject out = new JSONObject();
    out.put("msg", trules.getMessage());
    out.put("id", ev.getId());

    // CHANGED: ts -> tg
    out.put("tg", ev.getTg());

    // NEW
    out.put("seq", ev.getSeq());

    out.put("val", ev.getValue());
    out.put("lat_ms", ev.getLatMs());
    out.put("tsr_esper", ev.getTsrEsper());
    out.put("tsn_esper", ev.getTsnEsper());

    // Drop counters snapshot (from Receiver static counters)
    JSONObject drops = new JSONObject();
    drops.put("total", Receiver.getDroppedTotal());
    drops.put("missing_tg", Receiver.getDroppedMissingTg());
    drops.put("late", Receiver.getDroppedLate());
    drops.put("overflow", Receiver.getDroppedOverflow());
    out.put("cep_drops", drops);

    String pubMessage = out.toString();

    for (int i = 0; i < this.trules.getlOutputTopic().size(); i++) {
      publisher.Publish(pubMessage, trules.getlOutputTopic().get(i), trules.getClient());
    }
  }

  public RuleManager getTrules() {
    return trules;
  }

  public void setTrules(RuleManager trules) {
    this.trules = trules;
  }

}
