package it.osint.raven.services;

import it.osint.raven.config.EndpointConfiguration;
import it.osint.raven.config.QdrantConfiguration;
import it.osint.raven.config.RavenConfiguration;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.time.Duration;
import java.util.List;

public class ConnectionStatusService {

    private static final Duration DEFAULT_TIMEOUT = Duration.ofMillis(250);

    public List<ConnectionProbe> check(RavenConfiguration configuration) {
        return check(configuration, DEFAULT_TIMEOUT);
    }

    List<ConnectionProbe> check(RavenConfiguration configuration, Duration timeout) {
        EndpointConfiguration neo4j = configuration.getNeo4j();
        QdrantConfiguration qdrant = configuration.getQdrant();
        EndpointConfiguration mongodb = configuration.getMongodb();

        return List.of(
                probe("Neo4j", neo4j.getHost(), neo4j.getPort(), timeout),
                probe("Qdrant HTTP", qdrant.getHost(), qdrant.getHttpPort(), timeout),
                probe("Qdrant gRPC", qdrant.getHost(), qdrant.getGrpcPort(), timeout),
                probe("MongoDB", mongodb.getHost(), mongodb.getPort(), timeout)
        );
    }

    private static ConnectionProbe probe(String name, String host, int port, Duration timeout) {
        if (host == null || host.isBlank() || port <= 0 || port > 65535) {
            return new ConnectionProbe(name, String.valueOf(host), port, ConnectionState.INVALID);
        }

        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, port), Math.toIntExact(timeout.toMillis()));
            return new ConnectionProbe(name, host, port, ConnectionState.ONLINE);
        } catch (IOException | IllegalArgumentException ex) {
            return new ConnectionProbe(name, host, port, ConnectionState.OFFLINE);
        }
    }
}
