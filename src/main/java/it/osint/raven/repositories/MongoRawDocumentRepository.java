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
import it.osint.raven.dto.source.RawDocumentDto;
import it.osint.raven.utils.OsintObjectMapper;
import org.bson.Document;
import org.bson.conversions.Bson;

import java.net.URI;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

public class MongoRawDocumentRepository implements RawDocumentRepository, AutoCloseable {

    public static final String COLLECTION_NAME = "raw_documents";

    private static final TypeReference<Map<String, Object>> DOCUMENT_MAP_TYPE = new TypeReference<>() {
    };
    private static final ReplaceOptions UPSERT = new ReplaceOptions().upsert(true);

    private final MongoClient ownedMongoClient;
    private final MongoCollection<Document> collection;
    private final ObjectMapper objectMapper;

    public MongoRawDocumentRepository(RavenConfiguration configuration) {
        MongoDatabaseFactory databaseFactory = new MongoDatabaseFactory();
        MongoClient mongoClient = databaseFactory.createClient(configuration);
        this.ownedMongoClient = mongoClient;
        this.collection = databaseFactory.ravenDatabase(mongoClient).getCollection(COLLECTION_NAME);
        this.objectMapper = OsintObjectMapper.create();
        initializeStorage();
    }

    public MongoRawDocumentRepository(MongoDatabase database) {
        this(database, OsintObjectMapper.create());
    }

    MongoRawDocumentRepository(MongoDatabase database, ObjectMapper objectMapper) {
        this.ownedMongoClient = null;
        this.collection = database.getCollection(COLLECTION_NAME);
        this.objectMapper = objectMapper;
        initializeStorage();
    }

    public final void initializeStorage() {
        collection.createIndexes(List.of(
                new IndexModel(
                        Indexes.ascending("source_id", "original_uri"),
                        new IndexOptions().name("raw_documents_source_uri_unique").unique(true).sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("source_id", "content_hash"),
                        new IndexOptions().name("raw_documents_source_hash_unique").unique(true).sparse(true)
                ),
                new IndexModel(
                        Indexes.descending("acquisition_time"),
                        new IndexOptions().name("raw_documents_acquisition_time_idx").sparse(true)
                ),
                new IndexModel(
                        Indexes.descending("content_timestamp"),
                        new IndexOptions().name("raw_documents_content_timestamp_idx").sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("mime_type"),
                        new IndexOptions().name("raw_documents_mime_type_idx").sparse(true)
                )
        ));
    }

    @Override
    public RawDocumentDto save(RawDocumentDto rawDocument) {
        Objects.requireNonNull(rawDocument, "rawDocument must not be null");
        if (rawDocument.getId() == null) {
            rawDocument.setId(UUID.randomUUID());
        }
        if (rawDocument.getAcquisitionTime() == null) {
            rawDocument.setAcquisitionTime(Instant.now());
        }

        Document document = toDocument(rawDocument);
        collection.replaceOne(Filters.eq("_id", rawDocument.getId().toString()), document, UPSERT);
        return rawDocument;
    }

    @Override
    public Optional<RawDocumentDto> findById(UUID id) {
        Objects.requireNonNull(id, "id must not be null");
        return findOne(Filters.eq("_id", id.toString()));
    }

    @Override
    public Optional<RawDocumentDto> findBySourceIdAndOriginalUri(UUID sourceId, URI originalUri) {
        Objects.requireNonNull(sourceId, "sourceId must not be null");
        Objects.requireNonNull(originalUri, "originalUri must not be null");
        return findOne(Filters.and(
                Filters.eq("source_id", sourceId.toString()),
                Filters.eq("original_uri", originalUri.toString())
        ));
    }

    @Override
    public Optional<RawDocumentDto> findBySourceIdAndContentHash(UUID sourceId, String contentHash) {
        Objects.requireNonNull(sourceId, "sourceId must not be null");
        Objects.requireNonNull(contentHash, "contentHash must not be null");
        return findOne(Filters.and(
                Filters.eq("source_id", sourceId.toString()),
                Filters.eq("content_hash", contentHash)
        ));
    }

    @Override
    public List<RawDocumentDto> findBySourceId(UUID sourceId, int limit) {
        Objects.requireNonNull(sourceId, "sourceId must not be null");
        return toRawDocuments(collection.find(Filters.eq("source_id", sourceId.toString()))
                .sort(rawDocumentSort())
                .limit(normalizeLimit(limit)));
    }

    @Override
    public List<RawDocumentDto> findRecent(int limit) {
        return toRawDocuments(collection.find()
                .sort(rawDocumentSort())
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

    private Optional<RawDocumentDto> findOne(Bson filter) {
        Document document = collection.find(filter).first();
        return document == null ? Optional.empty() : Optional.of(toRawDocument(document));
    }

    private List<RawDocumentDto> toRawDocuments(FindIterable<Document> documents) {
        List<RawDocumentDto> rawDocuments = new ArrayList<>();
        for (Document document : documents) {
            rawDocuments.add(toRawDocument(document));
        }
        return rawDocuments;
    }

    private Document toDocument(RawDocumentDto rawDocument) {
        Map<String, Object> payload = objectMapper.convertValue(rawDocument, DOCUMENT_MAP_TYPE);
        Document document = new Document(payload);
        document.put("_id", rawDocument.getId().toString());
        return document;
    }

    private RawDocumentDto toRawDocument(Document document) {
        Document payload = new Document(document);
        payload.remove("_id");
        return objectMapper.convertValue(payload, RawDocumentDto.class);
    }

    private static Bson rawDocumentSort() {
        return Sorts.orderBy(
                Sorts.descending("content_timestamp"),
                Sorts.descending("acquisition_time")
        );
    }

    private static int normalizeLimit(int limit) {
        return limit > 0 ? limit : 100;
    }
}
