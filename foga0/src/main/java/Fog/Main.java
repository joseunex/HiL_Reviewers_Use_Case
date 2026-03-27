package Fog;

import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

public class Main {

  private static String getenvOrDefault(String key, String defaultValue) {
    String v = System.getenv(key);
    return (v == null || v.trim().isEmpty()) ? defaultValue : v.trim();
  }

  private static int getenvIntOrDefault(String key, int defaultValue) {
    String v = System.getenv(key);
    if (v == null || v.trim().isEmpty()) return defaultValue;
    try {
      return Integer.parseInt(v.trim());
    } catch (NumberFormatException ex) {
      System.err.println("Invalid integer for env " + key + ": '" + v + "'. Using default=" + defaultValue);
      return defaultValue;
    }
  }

  public static void main(String[] args) throws UnknownHostException {

    final String defaultBrokerUri =
      "tcp://mosquitto-foga0:1883";

    final String mqttBrokerUri  = getenvOrDefault("MQTT_BROKER_URI", defaultBrokerUri);

    final String defaultClientIdPrefix =
      "foga_0";
    final String clientIdPrefix = getenvOrDefault("MQTT_CLIENT_ID_PREFIX", defaultClientIdPrefix);
    final int randId = ThreadLocalRandom.current().nextInt(0, 9999999);
    final String clientId = clientIdPrefix + "_" + randId;

    final int socketTimeoutSec = getenvIntOrDefault("MQTT_SOCKET_TIMEOUT_SEC", 5);

    System.out.println("MQTT_BROKER_URI=" + mqttBrokerUri);
    System.out.println("MQTT_CLIENT_ID=" + clientId);
    System.out.println("MQTT_CLIENT_ID_PREFIX=" + clientIdPrefix);
    System.out.println("MQTT_SOCKET_TIMEOUT_SEC=" + socketTimeoutSec);

    List<Topic> Ltopic = new ArrayList<Topic>();
    Topic topic;

    topic = new Topic("Fog", true, true);
    Ltopic.add(topic);

    // FIX: suscripción al topic global de ACKs de actuadores
    topic = new Topic("actuators/ack", true, false);
    Ltopic.add(topic);

      topic = new Topic("B",
        true,
        false
      );
      Ltopic.add(topic);
      topic = new Topic("Z",
        true,
        true
      );
      Ltopic.add(topic);
      topic = new Topic("C",
        true,
        false
      );
      Ltopic.add(topic);

    List<Broker> Lbroker = new ArrayList<Broker>();
    Broker broker;
    broker = new Broker(mqttBrokerUri, Ltopic);
    Lbroker.add(broker);

    GestorDeConexiones gestorconexiones = new GestorDeConexiones(clientId, Lbroker);
    gestorconexiones.Iniciar();

    Publisher publisher = new Publisher();

      final String defaultMongoUri =
        "mongodb://fogfoga0-mongo:27017";
      final String mongoUri = getenvOrDefault("MONGO_URI", defaultMongoUri);

      System.out.println("MONGO_URI=" + mongoUri);

      MongoGestor mongogestor = new MongoGestor(clientIdPrefix, mongoUri);
      Receiver receiver = new Receiver(gestorconexiones, publisher, mqttBrokerUri, mongogestor, false);

  }
}
