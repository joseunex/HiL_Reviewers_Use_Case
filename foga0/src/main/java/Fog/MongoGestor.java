package Fog;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.concurrent.TimeUnit;

import org.bson.Document;

import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import java.util.Iterator;

public class MongoGestor {
    private MongoClient mongoCliente;
    private MongoDatabase baseDeDatos;
    private String fogID;
    
    public MongoGestor(String fogID, String connectionString) {
        this.fogID = fogID;
        //this.mongoCliente = createClient(mongourl);
        this.mongoCliente = connectToMongo(connectionString);
        this.baseDeDatos = this.mongoCliente.getDatabase("Fog_Node_" + fogID);
    }
    
    public MongoClient connectToMongo(String connectionString) {
        MongoClient mongoClient = MongoClients.create(connectionString);
        Iterator<String> databaseIterator = mongoClient.listDatabaseNames().iterator();
        if (databaseIterator.hasNext()) {
            System.out.println("Connected to MongoDB.");
            
            // You can access a specific database if needed
            //MongoDatabase database = mongoClient.getDatabase("your_database_name");
        } else {
            System.out.println("Failed to connect to MongoDB.");
        }
        
        return mongoClient;
    }
    
    public void appendDocument(String message, String collection) {
        MongoCollection<Document> collect = baseDeDatos.getCollection(collection);
        Document dato = new Document();
        dato.append("value", message);
        Date date = new Date();
        SimpleDateFormat sdf = new SimpleDateFormat("MM/dd/yyyy h:mm:ss a");
        String formattedDate = sdf.format(date);
        dato.append("timeStamp", formattedDate);
        collect.insertOne(dato);
    }
    
    public void appenJsonDocument(String json, String topic) {
        Document dbObject = Document.parse(json);
        MongoCollection<Document> collect = baseDeDatos.getCollection(topic);
        collect.insertOne(dbObject);
    }
    
    public MongoClient getMongoCliente() {
        return mongoCliente;
    }
    
    public void setMongoCliente(MongoClient mongoCliente) {
        this.mongoCliente = mongoCliente;
    }
    
    public MongoDatabase getBaseDeDatos() {
        return baseDeDatos;
    }
    
    public void setBaseDeDatos(MongoDatabase baseDeDatos) {
        this.baseDeDatos = baseDeDatos;
    }
    
    public String getFogID() {
        return fogID;
    }
    
    public void setFogID(String fogID) {
        this.fogID = fogID;
    }
    
    private MongoClient createClient(String mongourl) {
        return MongoClients.create(mongourl);
    }
}
