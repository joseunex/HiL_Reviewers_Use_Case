package EsperClient;

public class majorthan82 extends Event {

  // CHANGED: include tg + seq
  public majorthan82(String id, long tg, long seq, int value, long latMs, long tsrEsper) {
    super(id, tg, seq, value, latMs, tsrEsper);
  }
}
