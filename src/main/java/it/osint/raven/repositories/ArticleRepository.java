package it.osint.raven.repositories;

import it.osint.raven.dto.article.ArticleDto;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ArticleRepository {

    ArticleDto save(ArticleDto article);

    Optional<ArticleDto> findById(UUID id);

    Optional<ArticleDto> findByRawDocumentId(UUID rawDocumentId);

    List<ArticleDto> findByTaxonomyDomain(String domain, int limit);

    List<ArticleDto> findByEventType(String eventType, int limit);

    List<ArticleDto> findByEntityNormalizedName(String normalizedName, int limit);

    List<ArticleDto> findRecent(int limit);

    boolean deleteById(UUID id);
}
