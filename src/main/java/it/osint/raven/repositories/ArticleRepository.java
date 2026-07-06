package it.osint.raven.repositories;

import it.osint.raven.dto.article.ArticleDto;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.mongodb.repository.Query;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ArticleRepository extends MongoRepository<ArticleDto, UUID> {

    Sort ARTICLE_SORT = Sort.by(
            Sort.Order.desc("metadata.publicationDate"),
            Sort.Order.desc("provenance.extractionTime")
    );

    int DEFAULT_LIMIT = 100;

    Optional<ArticleDto> findByRawDocumentId(UUID rawDocumentId);

    @Query("{ 'taxonomy.domain': ?0 }")
    List<ArticleDto> findByTaxonomyDomain(String domain, Pageable pageable);

    @Query("{ 'events.type': ?0 }")
    List<ArticleDto> findByEventType(String eventType, Pageable pageable);

    @Query("{ 'entities.normalized_name': ?0 }")
    List<ArticleDto> findByEntityNormalizedName(String normalizedName, Pageable pageable);

    @Query("{}")
    List<ArticleDto> findRecent(Pageable pageable);

    default List<ArticleDto> findByTaxonomyDomain(String domain, int limit) {
        return findByTaxonomyDomain(domain, page(limit));
    }

    default List<ArticleDto> findByEventType(String eventType, int limit) {
        return findByEventType(eventType, page(limit));
    }

    default List<ArticleDto> findByEntityNormalizedName(String normalizedName, int limit) {
        return findByEntityNormalizedName(normalizedName, page(limit));
    }

    default List<ArticleDto> findRecent(int limit) {
        return findRecent(page(limit));
    }

    default boolean deleteExistingById(UUID id) {
        if (!existsById(id)) {
            return false;
        }
        deleteById(id);
        return true;
    }

    private static Pageable page(int limit) {
        return PageRequest.of(0, limit > 0 ? limit : DEFAULT_LIMIT, ARTICLE_SORT);
    }
}
