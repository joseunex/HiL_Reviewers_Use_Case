package EsperClient;

public class Event {
  private String id;        // sensor id
  private long tg;          // generation timestamp (origin)  <-- CHANGED
  private long seq;         // per-sensor sequence number     <-- NEW
  private double value;     // val
  private long latMs;       // lat_ms from payload (if any)

  private long tsrEsper;    // reception time in Esper (ms)
  private long tsnEsper;    // notification time (ms), set in listener

  // CHANGED: include tg + seq
  public Event(String id, long tg, long seq, double value, long latMs, long tsrEsper) {
    this.id = id;
    this.tg = tg;
    this.seq = seq;
    this.value = value;
    this.latMs = latMs;
    this.tsrEsper = tsrEsper;
    this.tsnEsper = -1L;
  }

  public String getId() { return id; }

  // CHANGED: getTs -> getTg (Esper property becomes "tg")
  public long getTg() { return tg; }

  // NEW
  public long getSeq() { return seq; }

  public double getValue() { return value; }
  public long getLatMs() { return latMs; }

  public long getTsrEsper() { return tsrEsper; }
  public long getTsnEsper() { return tsnEsper; }
  public void setTsnEsper(long tsnEsper) { this.tsnEsper = tsnEsper; }
}
