package Gestores;

import java.util.concurrent.atomic.AtomicBoolean;

import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttCallback;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.json.JSONObject;

/**
 * Receiver para el sensor de lazo cerrado.
 *
 * Escucha en "actuators/ack" y extrae el campo "applied_state"
 * del objeto "actuator" del JSON recibido.
 *
 * Actualiza el AtomicBoolean compartido con el SensorThread:
 *   applied_state == "ON"  → coolingOn = true  (refrigeración activa)
 *   applied_state == "OFF" → coolingOn = false  (refrigeración inactiva)
 */
public class Receiver implements MqttCallback {
    private Publisher pub;
    private GestorDeConexiones gestorconexiones;
    private AtomicBoolean coolingOn;

    public Receiver(GestorDeConexiones gestorconexiones, Publisher pub, AtomicBoolean coolingOn) {
        this.gestorconexiones = gestorconexiones;
        this.pub = pub;
        this.coolingOn = coolingOn;
        for (int i = 0; i < this.gestorconexiones.getLclient().size(); i++) {
            this.gestorconexiones.getLclient().get(i).setCallback(this);
        }
    }

    public void connectionLost(Throwable cause) {
        System.out.println("CLOSED_LOOP_SENSOR " + gestorconexiones.getIDcliente()
                + " | Connection lost: " + cause.getMessage());
    }

    public void messageArrived(String topic, MqttMessage message) throws Exception {
        String dataReceived = new String(message.getPayload());
        System.out.println("CLOSED_LOOP_SENSOR " + gestorconexiones.getIDcliente()
                + " | ACK received: " + dataReceived + " | From topic: " + topic);

        try {
            JSONObject json = new JSONObject(dataReceived);

            // Extraer applied_state del objeto "actuator"
            if (json.has("actuator")) {
                JSONObject actuator = json.getJSONObject("actuator");
                if (actuator.has("applied_state")) {
                    String state = actuator.getString("applied_state");
                    boolean newCooling = state.equalsIgnoreCase("ON");
                    boolean oldCooling = coolingOn.getAndSet(newCooling);

                    if (oldCooling != newCooling) {
                        System.out.println("CLOSED_LOOP_SENSOR " + gestorconexiones.getIDcliente()
                                + " | Cooling state changed: " + oldCooling + " -> " + newCooling);
                    }
                }
            }
        } catch (Exception e) {
            System.out.println("CLOSED_LOOP_SENSOR " + gestorconexiones.getIDcliente()
                    + " | Error parsing ACK: " + e.getMessage());
        }
    }

    public void deliveryComplete(IMqttDeliveryToken token) {
        // No-op
    }
}
