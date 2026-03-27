package Fog;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import org.json.JSONArray;
import org.json.JSONObject;

import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoCursor;
import org.bson.Document;

public class Redirection implements Runnable {
    GestorDeConexiones gestordeconexiones;
    MongoGestor mongogestor;
    Receiver receiv;
    int redirectionTime;

    Redirection(int redirectionTime, GestorDeConexiones gestordeconexiones, MongoGestor mongogestor, Receiver receiv) {
        this.redirectionTime = redirectionTime;
        this.gestordeconexiones = gestordeconexiones;
        this.mongogestor = mongogestor;
        this.receiv = receiv;
    }

    public void run() {
        List<String> lroute = new ArrayList<String>();
        boolean redirectionable = false;
        JSONArray arr = null;

        while (true) {
            System.out.println("Iterating in Redirection");
            MongoCollection<Document> collection = mongogestor.getBaseDeDatos().getCollection("FogCollection");
            MongoCursor<Document> cursor = collection.find().iterator();

            while (cursor.hasNext()) {
                Document document = cursor.next();
                try {
                    JSONObject jsonmessage = new JSONObject(document.toJson());
                    redirectionable = true;
                    System.out.println(document.toJson());
                    arr = jsonmessage.getJSONArray("route");
                } catch (Exception e) {
                    System.out.println("Record without redirection format, skipping to the next element...");
                    redirectionable = false;
                }
                if (redirectionable) {
                    receiv.RedirectToFog(document.toJson());
                    if (!receiv.getFogUrl().equals(arr.get(arr.length() - 1))) {
                        collection.deleteOne(document);
                    }
                }
            }

            try {
                Thread.sleep((int) (this.redirectionTime * 1000 / 1.0));
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
    }
}
