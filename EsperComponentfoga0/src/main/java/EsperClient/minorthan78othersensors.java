package EsperClient;

public class minorthan78othersensors extends Event {

  // CHANGED: include tg + seq
  public minorthan78othersensors(String id, long tg, long seq, int value, long latMs, long tsrEsper) {
    super(id, tg, seq, value, latMs, tsrEsper);
  }
}
