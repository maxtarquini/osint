package it.osint.raven.repositories;

import it.osint.raven.dto.source.SourceDto;
import it.osint.raven.dto.source.SourceStatus;
import it.osint.raven.dto.source.SourceType;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface SourceRepository {

    SourceDto save(SourceDto source);

    Optional<SourceDto> findById(UUID id);

    Optional<SourceDto> findByName(String name);

    List<SourceDto> findByStatus(SourceStatus status, int limit);

    List<SourceDto> findByType(SourceType type, int limit);

    List<SourceDto> findEnabledOrderedByPriority(int limit);

    boolean deleteById(UUID id);
}
