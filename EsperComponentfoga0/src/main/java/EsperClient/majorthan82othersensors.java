package EsperClient;

public class majorthan82othersensors extends Event {

  // CHANGED: include tg + seq
  public majorthan82othersensors(String id, long tg, long seq, int value, long latMs, long tsrEsper) {
    super(id, tg, seq, value, latMs, tsrEsper);
  }
}
