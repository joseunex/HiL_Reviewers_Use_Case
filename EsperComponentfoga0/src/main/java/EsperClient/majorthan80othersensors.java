package EsperClient;

public class majorthan80othersensors extends Event {

  // CHANGED: include tg + seq
  public majorthan80othersensors(String id, long tg, long seq, double value, long latMs, long tsrEsper) {
    super(id, tg, seq, value, latMs, tsrEsper);
  }
}
