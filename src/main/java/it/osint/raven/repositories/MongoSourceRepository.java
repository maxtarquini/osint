package it.osint.raven.repositories;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mongodb.client.FindIterable;
import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import com.mongodb.client.model.Filters;
import com.mongodb.client.model.IndexModel;
import com.mongodb.client.model.IndexOptions;
import com.mongodb.client.model.Indexes;
import com.mongodb.client.model.ReplaceOptions;
import com.mongodb.client.model.Sorts;
import it.osint.raven.config.RavenConfiguration;
import it.osint.raven.dto.source.SourceDto;
import it.osint.raven.dto.source.SourceStatus;
import it.osint.raven.dto.source.SourceType;
import it.osint.raven.utils.OsintObjectMapper;
import org.bson.Document;
import org.bson.conversions.Bson;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

public class MongoSourceRepository implements SourceRepository, AutoCloseable {

    public static final String COLLECTION_NAME = "sources";

    private static final TypeReference<Map<String, Object>> DOCUMENT_MAP_TYPE = new TypeReference<>() {
    };
    private static final ReplaceOptions UPSERT = new ReplaceOptions().upsert(true);

    private final MongoClient ownedMongoClient;
    private final MongoCollection<Document> collection;
    private final ObjectMapper objectMapper;

    public MongoSourceRepository(RavenConfiguration configuration) {
        MongoDatabaseFactory databaseFactory = new MongoDatabaseFactory();
        MongoClient mongoClient = databaseFactory.createClient(configuration);
        this.ownedMongoClient = mongoClient;
        this.collection = databaseFactory.ravenDatabase(mongoClient).getCollection(COLLECTION_NAME);
        this.objectMapper = OsintObjectMapper.create();
        initializeStorage();
    }

    public MongoSourceRepository(MongoDatabase database) {
        this(database, OsintObjectMapper.create());
    }

    MongoSourceRepository(MongoDatabase database, ObjectMapper objectMapper) {
        this.ownedMongoClient = null;
        this.collection = database.getCollection(COLLECTION_NAME);
        this.objectMapper = objectMapper;
        initializeStorage();
    }

    public final void initializeStorage() {
        collection.createIndexes(List.of(
                new IndexModel(
                        Indexes.ascending("name"),
                        new IndexOptions().name("sources_name_unique").unique(true).sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("type", "endpoint"),
                        new IndexOptions().name("sources_type_endpoint_idx").sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("status", "priority"),
                        new IndexOptions().name("sources_status_priority_idx").sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("tags"),
                        new IndexOptions().name("sources_tags_idx").sparse(true)
                )
        ));
    }

    @Override
    public SourceDto save(SourceDto source) {
        Objects.requireNonNull(source, "source must not be null");
        if (source.getId() == null) {
            source.setId(UUID.randomUUID());
        }

        Document document = toDocument(source);
        collection.replaceOne(Filters.eq("_id", source.getId().toString()), document, UPSERT);
        return source;
    }

    @Override
    public Optional<SourceDto> findById(UUID id) {
        Objects.requireNonNull(id, "id must not be null");
        return findOne(Filters.eq("_id", id.toString()));
    }

    @Override
    public Optional<SourceDto> findByName(String name) {
        Objects.requireNonNull(name, "name must not be null");
        return findOne(Filters.eq("name", name));
    }

    @Override
    public List<SourceDto> findByStatus(SourceStatus status, int limit) {
        Objects.requireNonNull(status, "status must not be null");
        return toSources(collection.find(Filters.eq("status", status.name()))
                .sort(sourceSort())
                .limit(normalizeLimit(limit)));
    }

    @Override
    public List<SourceDto> findByType(SourceType type, int limit) {
        Objects.requireNonNull(type, "type must not be null");
        return toSources(collection.find(Filters.eq("type", type.name()))
                .sort(sourceSort())
                .limit(normalizeLimit(limit)));
    }

    @Override
    public List<SourceDto> findEnabledOrderedByPriority(int limit) {
        return toSources(collection.find(Filters.eq("status", SourceStatus.ENABLED.name()))
                .sort(sourceSort())
                .limit(normalizeLimit(limit)));
    }

    @Override
    public boolean deleteById(UUID id) {
        Objects.requireNonNull(id, "id must not be null");
        return collection.deleteOne(Filters.eq("_id", id.toString())).getDeletedCount() > 0;
    }

    @Override
    public void close() {
        if (ownedMongoClient != null) {
            ownedMongoClient.close();
        }
    }

    private Optional<SourceDto> findOne(Bson filter) {
        Document document = collection.find(filter).first();
        return document == null ? Optional.empty() : Optional.of(toSource(document));
    }

    private List<SourceDto> toSources(FindIterable<Document> documents) {
        List<SourceDto> sources = new ArrayList<>();
        for (Document document : documents) {
            sources.add(toSource(document));
        }
        return sources;
    }

    private Document toDocument(SourceDto source) {
        Map<String, Object> payload = objectMapper.convertValue(source, DOCUMENT_MAP_TYPE);
        Document document = new Document(payload);
        document.put("_id", source.getId().toString());
        return document;
    }

    private SourceDto toSource(Document document) {
        Document payload = new Document(document);
        payload.remove("_id");
        return objectMapper.convertValue(payload, SourceDto.class);
    }

    private static Bson sourceSort() {
        return Sorts.orderBy(
                Sorts.ascending("priority"),
                Sorts.ascending("name")
        );
    }

    private static int normalizeLimit(int limit) {
        return limit > 0 ? limit : 100;
    }
}
