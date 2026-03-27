package EsperClient;

public class majorthan50 extends Event {

  // CHANGED: include tg + seq
  public majorthan50(String id, long tg, long seq, int value, long latMs, long tsrEsper) {
    super(id, tg, seq, value, latMs, tsrEsper);
  }
}
