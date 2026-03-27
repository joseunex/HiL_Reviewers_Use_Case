package EsperClient;

public class minorthan79 extends Event {

  // CHANGED: include tg + seq
  public minorthan79(String id, long tg, long seq, double value, long latMs, long tsrEsper) {
    super(id, tg, seq, value, latMs, tsrEsper);
  }
}
