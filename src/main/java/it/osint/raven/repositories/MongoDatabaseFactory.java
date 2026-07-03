package it.osint.raven.repositories;

import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoDatabase;
import it.osint.raven.config.EndpointConfiguration;
import it.osint.raven.config.RavenConfiguration;

public class MongoDatabaseFactory {

    public static final String RAVEN_DATABASE_NAME = "raven";

    public MongoClient createClient(RavenConfiguration configuration) {
        EndpointConfiguration mongodb = configuration.getMongodb();
        return MongoClients.create("mongodb://%s:%d".formatted(mongodb.getHost(), mongodb.getPort()));
    }

    public MongoDatabase ravenDatabase(MongoClient mongoClient) {
        return mongoClient.getDatabase(RAVEN_DATABASE_NAME);
    }
}
