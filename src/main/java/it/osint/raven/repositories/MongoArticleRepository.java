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
import it.osint.raven.dto.article.ArticleDto;
import it.osint.raven.utils.article.ArticleObjectMapper;
import org.bson.Document;
import org.bson.conversions.Bson;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

public class MongoArticleRepository implements ArticleRepository, AutoCloseable {

    public static final String COLLECTION_NAME = "articles";

    private static final TypeReference<Map<String, Object>> DOCUMENT_MAP_TYPE = new TypeReference<>() {
    };
    private static final ReplaceOptions UPSERT = new ReplaceOptions().upsert(true);

    private final MongoClient ownedMongoClient;
    private final MongoCollection<Document> collection;
    private final ObjectMapper objectMapper;

    public MongoArticleRepository(RavenConfiguration configuration) {
        MongoDatabaseFactory databaseFactory = new MongoDatabaseFactory();
        MongoClient mongoClient = databaseFactory.createClient(configuration);
        this.ownedMongoClient = mongoClient;
        this.collection = databaseFactory.ravenDatabase(mongoClient).getCollection(COLLECTION_NAME);
        this.objectMapper = ArticleObjectMapper.create();
        initializeStorage();
    }

    public MongoArticleRepository(MongoDatabase database) {
        this(database, ArticleObjectMapper.create());
    }

    MongoArticleRepository(MongoDatabase database, ObjectMapper objectMapper) {
        this.ownedMongoClient = null;
        this.collection = database.getCollection(COLLECTION_NAME);
        this.objectMapper = objectMapper;
        initializeStorage();
    }

    public final void initializeStorage() {
        collection.createIndexes(List.of(
                new IndexModel(
                        Indexes.ascending("raw_document_id"),
                        new IndexOptions().name("articles_raw_document_id_unique").unique(true).sparse(true)
                ),
                new IndexModel(
                        Indexes.descending("metadata.publication_date"),
                        new IndexOptions().name("articles_publication_date_idx").sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("taxonomy.domain", "taxonomy.sub_domain", "taxonomy.event_type"),
                        new IndexOptions().name("articles_taxonomy_idx").sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("entities.normalized_name", "entities.type"),
                        new IndexOptions().name("articles_entities_idx").sparse(true)
                ),
                new IndexModel(
                        Indexes.ascending("events.type", "events.date"),
                        new IndexOptions().name("articles_events_idx").sparse(true)
                )
        ));
    }

    @Override
    public ArticleDto save(ArticleDto article) {
        Objects.requireNonNull(article, "article must not be null");
        if (article.getId() == null) {
            article.setId(UUID.randomUUID());
        }

        Document document = toDocument(article);
        collection.replaceOne(Filters.eq("_id", article.getId().toString()), document, UPSERT);
        return article;
    }

    @Override
    public Optional<ArticleDto> findById(UUID id) {
        Objects.requireNonNull(id, "id must not be null");
        return findOne(Filters.eq("_id", id.toString()));
    }

    @Override
    public Optional<ArticleDto> findByRawDocumentId(UUID rawDocumentId) {
        Objects.requireNonNull(rawDocumentId, "rawDocumentId must not be null");
        return findOne(Filters.eq("raw_document_id", rawDocumentId.toString()));
    }

    @Override
    public List<ArticleDto> findByTaxonomyDomain(String domain, int limit) {
        Objects.requireNonNull(domain, "domain must not be null");
        return toArticles(collection.find(Filters.eq("taxonomy.domain", domain))
                .sort(articleSort())
                .limit(normalizeLimit(limit)));
    }

    @Override
    public List<ArticleDto> findByEventType(String eventType, int limit) {
        Objects.requireNonNull(eventType, "eventType must not be null");
        return toArticles(collection.find(Filters.eq("events.type", eventType))
                .sort(articleSort())
                .limit(normalizeLimit(limit)));
    }

    @Override
    public List<ArticleDto> findByEntityNormalizedName(String normalizedName, int limit) {
        Objects.requireNonNull(normalizedName, "normalizedName must not be null");
        return toArticles(collection.find(Filters.eq("entities.normalized_name", normalizedName))
                .sort(articleSort())
                .limit(normalizeLimit(limit)));
    }

    @Override
    public List<ArticleDto> findRecent(int limit) {
        return toArticles(collection.find()
                .sort(articleSort())
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

    private Optional<ArticleDto> findOne(Bson filter) {
        Document document = collection.find(filter).first();
        return document == null ? Optional.empty() : Optional.of(toArticle(document));
    }

    private List<ArticleDto> toArticles(FindIterable<Document> documents) {
        List<ArticleDto> articles = new ArrayList<>();
        for (Document document : documents) {
            articles.add(toArticle(document));
        }
        return articles;
    }

    private Document toDocument(ArticleDto article) {
        Map<String, Object> payload = objectMapper.convertValue(article, DOCUMENT_MAP_TYPE);
        Document document = new Document(payload);
        document.put("_id", article.getId().toString());
        return document;
    }

    private ArticleDto toArticle(Document document) {
        Document payload = new Document(document);
        payload.remove("_id");
        return objectMapper.convertValue(payload, ArticleDto.class);
    }

    private static int normalizeLimit(int limit) {
        return limit > 0 ? limit : 100;
    }

    private static Bson articleSort() {
        return Sorts.orderBy(
                Sorts.descending("metadata.publication_date"),
                Sorts.descending("provenance.extraction_time")
        );
    }
}
