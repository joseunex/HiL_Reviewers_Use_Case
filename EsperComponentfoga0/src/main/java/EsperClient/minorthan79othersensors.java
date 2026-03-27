package EsperClient;

public class minorthan79othersensors extends Event {

  // CHANGED: include tg + seq
  public minorthan79othersensors(String id, long tg, long seq, double value, long latMs, long tsrEsper) {
    super(id, tg, seq, value, latMs, tsrEsper);
  }
}
