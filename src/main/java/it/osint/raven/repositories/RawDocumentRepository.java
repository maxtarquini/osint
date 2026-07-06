package it.osint.raven.repositories;

import it.osint.raven.dto.source.RawDocumentDto;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.mongodb.repository.Query;

import java.net.URI;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface RawDocumentRepository extends MongoRepository<RawDocumentDto, UUID> {

    Sort RAW_DOCUMENT_SORT = Sort.by(
            Sort.Order.desc("contentTimestamp"),
            Sort.Order.desc("acquisitionTime")
    );

    int DEFAULT_LIMIT = 100;

    Optional<RawDocumentDto> findBySourceIdAndOriginalUri(UUID sourceId, URI originalUri);

    Optional<RawDocumentDto> findBySourceIdAndContentHash(UUID sourceId, String contentHash);

    List<RawDocumentDto> findBySourceId(UUID sourceId, Pageable pageable);

    @Query("{}")
    List<RawDocumentDto> findRecent(Pageable pageable);

    default List<RawDocumentDto> findBySourceId(UUID sourceId, int limit) {
        return findBySourceId(sourceId, page(limit));
    }

    default List<RawDocumentDto> findRecent(int limit) {
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
        return PageRequest.of(0, limit > 0 ? limit : DEFAULT_LIMIT, RAW_DOCUMENT_SORT);
    }
}
