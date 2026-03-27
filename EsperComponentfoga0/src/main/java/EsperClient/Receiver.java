package EsperClient;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttCallback;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.json.JSONObject;

public class Receiver implements MqttCallback {

  Publisher pub;
  GestorDeConexiones gestorconexiones;
  EsperComponent espercomponent;

  // --- buffering config ---
  private final long W_MS;            // bounded lateness
  private final long HOLD_MS;         // holding period for reordering
  private final int  MAX_EVENTS;      // bounded buffer size per topic
  private final long FLUSH_MS;        // flush period

  private final Map<String, ReorderBuffer> buffers = new ConcurrentHashMap<>();
  private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();

  // --- drop counters (thread-safe, accessible from MyListener) ---
  private static final AtomicLong droppedMissingTg   = new AtomicLong(0);
  private static final AtomicLong droppedLate        = new AtomicLong(0);
  private static final AtomicLong droppedOverflow     = new AtomicLong(0);
  private static final AtomicLong droppedTotal        = new AtomicLong(0);

  /** Total messages dropped (all reasons). */
  public static long getDroppedTotal()    { return droppedTotal.get(); }
  /** Dropped because tg was missing. */
  public static long getDroppedMissingTg(){ return droppedMissingTg.get(); }
  /** Dropped because |now - tg| > W_MS (late). */
  public static long getDroppedLate()     { return droppedLate.get(); }
  /** Dropped because reorder buffer overflow. */
  public static long getDroppedOverflow() { return droppedOverflow.get(); }

  public Receiver(GestorDeConexiones gestorconexiones, Publisher pub, EsperComponent esp) {
    this.gestorconexiones = gestorconexiones;
    this.pub = pub;
    this.espercomponent = esp;

    this.W_MS      = getLongEnv("CEP_LATENESS_W_MS", 5000L);
    this.HOLD_MS   = getLongEnv("CEP_REORDER_HOLD_MS", 50L);
    this.MAX_EVENTS= (int) getLongEnv("CEP_REORDER_MAX_EVENTS", 2000L);
    this.FLUSH_MS  = getLongEnv("CEP_REORDER_FLUSH_MS", 10L);

    System.out.println("CEP_LATENESS_W_MS=" + W_MS);
    System.out.println("CEP_REORDER_HOLD_MS=" + HOLD_MS);
    System.out.println("CEP_REORDER_MAX_EVENTS=" + MAX_EVENTS);
    System.out.println("CEP_REORDER_FLUSH_MS=" + FLUSH_MS);

    for (int i = 0; i < this.gestorconexiones.getLclient().size(); i++) {
      this.gestorconexiones.getLclient().get(i).setCallback(this);
    }

    // periodic flush (release to Esper)
    scheduler.scheduleAtFixedRate(() -> {
      try { flushAll(); } catch (Throwable t) { t.printStackTrace(); }
    }, FLUSH_MS, FLUSH_MS, TimeUnit.MILLISECONDS);
  }

  private static long getLongEnv(String key, long def) {
    try {
      String v = System.getenv(key);
      if (v == null || v.trim().isEmpty()) return def;
      return Long.parseLong(v.trim());
    } catch (Exception e) {
      return def;
    }
  }

  public void connectionLost(Throwable cause) {
    // optional: log
  }

  public void messageArrived(String topic, MqttMessage message) throws Exception {
    final long now = System.currentTimeMillis();
    final long tsrEsper = now; // reception time at CEP ingress

    String dataReceived = new String(message.getPayload());
    System.out.println("ESPER " + this.gestorconexiones.getIDcliente()
        + " | Received data: " + dataReceived + " |From topic: " + topic);

    JSONObject json = new JSONObject(dataReceived);

    String id  = json.optString("id", "");

    // CHANGED: ts -> tg (generation time)
    long tg    = json.optLong("tg", -1L);

    // NEW: seq (per-sensor sequence number)
    long seq   = json.optLong("seq", -1L);

    double value = json.getDouble("val");
    long latMs = json.optLong("lat_ms", -1L);

    if (tg < 0) {
      droppedMissingTg.incrementAndGet();
      droppedTotal.incrementAndGet();
      diagDrop("missing_tg", topic, id, tg, seq, now, latMs);
      return;
    }

    long diff = Math.abs(now - tg);
    if (diff > W_MS) {
      droppedLate.incrementAndGet();
      droppedTotal.incrementAndGet();
      diagDrop("late_out_of_W", topic, id, tg, seq, now, latMs);
      return;
    }

    PendingEvent pe = new PendingEvent(topic, id, tg, seq, value, latMs, tsrEsper);

    ReorderBuffer buf = buffers.computeIfAbsent(topic, t -> new ReorderBuffer(MAX_EVENTS));
    buf.add(pe);

    // enforce bounded size (drop oldest tg if overflow)
    PendingEvent dropped;
    while ((dropped = buf.dropOldestIfOverflow()) != null) {
      droppedOverflow.incrementAndGet();
      droppedTotal.incrementAndGet();
      diagDrop("buffer_overflow", dropped.topic, dropped.id, dropped.tg, dropped.seq, now, dropped.latMs);
    }
  }

  // Release to Esper based on watermark = now - HOLD_MS
  private void flushAll() {
    final long now = System.currentTimeMillis();
    final long watermark = now - HOLD_MS;

    for (ReorderBuffer buf : buffers.values()) {
      while (true) {
        PendingEvent pe = buf.pollEligible(watermark);
        if (pe == null) break;

        // CHANGED: include tg + seq
        messageToEsper(pe.id, pe.tg, pe.seq, pe.value, pe.latMs, pe.tsrEsper, pe.topic);
      }
    }
  }

  // minimal diagnostic (stdout). If you later want, you can publish to a diag topic here.
  private void diagDrop(String reason, String topic, String id, long tg, long seq, long now, long latMs) {
    System.out.println("ESPER_DIAG | drop_reason=" + reason
        + " | topic=" + topic
        + " | id=" + id
        + " | tg=" + tg
        + " | seq=" + seq
        + " | now=" + now
        + " | abs(now-tg)=" + Math.abs(now - tg)
        + " | lat_ms=" + latMs
        + " | dropped_total=" + droppedTotal.get());
  }

  // CHANGED: ts -> tg, and add seq
  public void messageToEsper(String id, long tg, long seq, double value, long latMs, long tsrEsper, String topic) {
    Event event = null;
    if(topic.equals("Z")){
    event = new majorthan80(id, tg, seq, value, latMs, tsrEsper);
    espercomponent.getEpService().getEPRuntime().sendEvent(event);
    event = new minorthan79(id, tg, seq, value, latMs, tsrEsper);
    espercomponent.getEpService().getEPRuntime().sendEvent(event);
    }
    if(topic.equals("C")){
    event = new majorthan80othersensors(id, tg, seq, value, latMs, tsrEsper);
    espercomponent.getEpService().getEPRuntime().sendEvent(event);
    event = new minorthan79othersensors(id, tg, seq, value, latMs, tsrEsper);
    espercomponent.getEpService().getEPRuntime().sendEvent(event);
    }
  }

  public void deliveryComplete(IMqttDeliveryToken token) { }

  // ------------------ helper structs ------------------

  private static final class PendingEvent {
    final String topic;
    final String id;
    final long tg;
    final long seq;
    final double value;
    final long latMs;
    final long tsrEsper;

    PendingEvent(String topic, String id, long tg, long seq, double value, long latMs, long tsrEsper) {
      this.topic = topic;
      this.id = id;
      this.tg = tg;
      this.seq = seq;
      this.value = value;
      this.latMs = latMs;
      this.tsrEsper = tsrEsper;
    }
  }

  private static final class ReorderBuffer {
    private final int max;
    private final PriorityQueue<PendingEvent> pq;

    ReorderBuffer(int max) {
      this.max = max;
      this.pq = new PriorityQueue<>(Comparator
          .comparingLong((PendingEvent e) -> e.tg)
          .thenComparingLong(e -> e.tsrEsper));
    }

    synchronized void add(PendingEvent e) {
      pq.add(e);
    }

    // eligible if tg <= watermark
    synchronized PendingEvent pollEligible(long watermark) {
      PendingEvent head = pq.peek();
      if (head == null) return null;
      if (head.tg <= watermark) return pq.poll();
      return null;
    }

    synchronized PendingEvent dropOldestIfOverflow() {
      if (pq.size() > max) return pq.poll(); // drop smallest tg (oldest)
      return null;
    }
  }
}
