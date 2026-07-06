package it.osint.raven.repositories;

import it.osint.raven.dto.source.SourceDto;
import it.osint.raven.dto.source.SourceStatus;
import it.osint.raven.dto.source.SourceType;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface SourceRepository extends MongoRepository<SourceDto, UUID> {

    Sort SOURCE_SORT = Sort.by(Sort.Direction.ASC, "priority", "name");

    int DEFAULT_LIMIT = 100;

    Optional<SourceDto> findByName(String name);

    List<SourceDto> findByStatus(SourceStatus status, Pageable pageable);

    List<SourceDto> findByType(SourceType type, Pageable pageable);

    default List<SourceDto> findByStatus(SourceStatus status, int limit) {
        return findByStatus(status, page(limit));
    }

    default List<SourceDto> findByType(SourceType type, int limit) {
        return findByType(type, page(limit));
    }

    default List<SourceDto> findEnabledOrderedByPriority(int limit) {
        return findByStatus(SourceStatus.ENABLED, page(limit));
    }

    default boolean deleteExistingById(UUID id) {
        if (!existsById(id)) {
            return false;
        }
        deleteById(id);
        return true;
    }

    private static Pageable page(int limit) {
        return PageRequest.of(0, limit > 0 ? limit : DEFAULT_LIMIT, SOURCE_SORT);
    }
}
