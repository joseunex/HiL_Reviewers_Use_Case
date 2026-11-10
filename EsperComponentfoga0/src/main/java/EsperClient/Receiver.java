package EsperClient;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.PriorityQueue;
import java.util.TreeSet;
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
  private final long STATS_MS;        // B2: period of the ESPER_STATS lines (0 = disabled)

  private final Map<String, ReorderBuffer> buffers = new ConcurrentHashMap<>();
  private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();
  private final ScheduledExecutorService statsScheduler = Executors.newSingleThreadScheduledExecutor(); // B2

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

  // B2: runtime statistics of the CEP ingress, reset at every ESPER_STATS line
  private final AtomicLong rxCount  = new AtomicLong(0);  // messages received
  private final AtomicLong relCount = new AtomicLong(0);  // events released to Esper
  private final AtomicLong procNs   = new AtomicLong(0);  // time spent processing released events (Esper + listeners + publications)
  private final AtomicLong bufMsSum = new AtomicLong(0);  // residence time in the reorder buffer, sum
  private final AtomicLong bufMsMax = new AtomicLong(0);  // residence time in the reorder buffer, max
  private long lastStatsNs = System.nanoTime();

  public Receiver(GestorDeConexiones gestorconexiones, Publisher pub, EsperComponent esp) {
    this.gestorconexiones = gestorconexiones;
    this.pub = pub;
    this.espercomponent = esp;

    this.W_MS      = getLongEnv("CEP_LATENESS_W_MS", 5000L);
    this.HOLD_MS   = getLongEnv("CEP_REORDER_HOLD_MS", 50L);
    this.MAX_EVENTS= (int) getLongEnv("CEP_REORDER_MAX_EVENTS", 2000L);
    this.FLUSH_MS  = getLongEnv("CEP_REORDER_FLUSH_MS", 10L);
    this.STATS_MS  = getLongEnv("CEP_STATS_MS", 1000L); // B2

    System.out.println("CEP_LATENESS_W_MS=" + W_MS);
    System.out.println("CEP_REORDER_HOLD_MS=" + HOLD_MS);
    System.out.println("CEP_REORDER_MAX_EVENTS=" + MAX_EVENTS);
    System.out.println("CEP_REORDER_FLUSH_MS=" + FLUSH_MS);
    System.out.println("CEP_STATS_MS=" + STATS_MS); // B2

    for (int i = 0; i < this.gestorconexiones.getLclient().size(); i++) {
      this.gestorconexiones.getLclient().get(i).setCallback(this);
    }

    // periodic flush (release to Esper)
    scheduler.scheduleAtFixedRate(() -> {
      try { flushAll(); } catch (Throwable t) { t.printStackTrace(); }
    }, FLUSH_MS, FLUSH_MS, TimeUnit.MILLISECONDS);

    // B2: periodic statistics, in their own thread so that they are reported even when the flush thread is busy
    if (STATS_MS > 0) {
      statsScheduler.scheduleAtFixedRate(() -> {
        try { logStats(); } catch (Throwable t) { t.printStackTrace(); }
      }, STATS_MS, STATS_MS, TimeUnit.MILLISECONDS);
    }
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
    rxCount.incrementAndGet(); // B2

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
  // B2: the eligible events of all topics are released in non-decreasing tg order (k-way merge of
  //     the per-topic buffers), and the watermark is refreshed before every release. Previously the
  //     topics were drained one after another with the watermark fixed at the start of the pass, so a
  //     backlog in one topic (background sensors) also delayed the release of the others (control loop).
  private void flushAll() {
    while (true) {
      final long watermark = System.currentTimeMillis() - HOLD_MS;

      ReorderBuffer next = null;
      long nextTg = Long.MAX_VALUE;
      for (ReorderBuffer buf : buffers.values()) {
        long tg = buf.peekEligibleTg(watermark);
        if (tg < nextTg) { nextTg = tg; next = buf; }
      }
      if (next == null) break;

      PendingEvent pe = next.pollEligible(watermark);
      if (pe == null) continue; // head removed meanwhile (overflow): look again

      long t0 = System.nanoTime();
      long residenceMs = System.currentTimeMillis() - pe.tsrEsper;
      // CHANGED: include tg + seq
      messageToEsper(pe.id, pe.tg, pe.seq, pe.value, pe.latMs, pe.tsrEsper, pe.topic);
      procNs.addAndGet(System.nanoTime() - t0);
      relCount.incrementAndGet();
      bufMsSum.addAndGet(residenceMs);
      bufMsMax.accumulateAndGet(residenceMs, Math::max);
    }
  }

  // B2: one line per period with the processing rates, the time blocked in publications, the
  //     utilisation of the release thread, the residence time in the reorder buffers, their
  //     occupancy per topic and the drop counters (parsed by analyze_experiment.py)
  private void logStats() {
    long nowNs = System.nanoTime();
    double periodMs = Math.max(1e-3, (nowNs - lastStatsNs) / 1e6);
    lastStatsNs = nowNs;

    long rx = rxCount.getAndSet(0);
    long rel = relCount.getAndSet(0);
    long proc = procNs.getAndSet(0);
    long bufSum = bufMsSum.getAndSet(0);
    long bufMax = bufMsMax.getAndSet(0);
    long pubOk = Publisher.published.getAndSet(0);
    long pubErr = Publisher.failed.getAndSet(0);
    long blkSum = Publisher.blockedUsSum.getAndSet(0);
    long blkMax = Publisher.blockedUsMax.getAndSet(0);

    StringBuilder sb = new StringBuilder("ESPER_STATS");
    sb.append(" | t=").append(System.currentTimeMillis());
    sb.append(" | period_ms=").append(fmt(periodMs));
    sb.append(" | rx=").append(rx);
    sb.append(" | rel=").append(rel);
    sb.append(" | pub=").append(pubOk);
    sb.append(" | pub_err=").append(pubErr);
    sb.append(" | pub_ms_mean=").append(fmt(pubOk + pubErr > 0 ? blkSum / 1000.0 / (pubOk + pubErr) : 0.0));
    sb.append(" | pub_ms_max=").append(fmt(blkMax / 1000.0));
    sb.append(" | util=").append(fmt(proc / 1e6 / periodMs));
    sb.append(" | buf_ms_mean=").append(fmt(rel > 0 ? (double) bufSum / rel : 0.0));
    sb.append(" | buf_ms_max=").append(bufMax);
    long occ = 0;
    StringBuilder perTopic = new StringBuilder();
    for (String topic : new TreeSet<>(buffers.keySet())) {
      int n = buffers.get(topic).size();
      occ += n;
      perTopic.append(" | occ_").append(topic).append('=').append(n);
    }
    sb.append(" | occ=").append(occ).append(perTopic);
    sb.append(" | drop_overflow=").append(droppedOverflow.get());
    sb.append(" | drop_late=").append(droppedLate.get());
    sb.append(" | drop_missing_tg=").append(droppedMissingTg.get());
    System.out.println(sb.toString());
  }

  private static String fmt(double v) {
    return String.format(Locale.ROOT, "%.3f", v);
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

    // B2: tg of the head if it is eligible, Long.MAX_VALUE otherwise
    synchronized long peekEligibleTg(long watermark) {
      PendingEvent head = pq.peek();
      return (head != null && head.tg <= watermark) ? head.tg : Long.MAX_VALUE;
    }

    synchronized int size() { return pq.size(); } // B2

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
