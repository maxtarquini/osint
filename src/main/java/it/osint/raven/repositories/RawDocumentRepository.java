package it.osint.raven.repositories;

import it.osint.raven.dto.source.RawDocumentDto;

import java.net.URI;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface RawDocumentRepository {

    RawDocumentDto save(RawDocumentDto rawDocument);

    Optional<RawDocumentDto> findById(UUID id);

    Optional<RawDocumentDto> findBySourceIdAndOriginalUri(UUID sourceId, URI originalUri);

    Optional<RawDocumentDto> findBySourceIdAndContentHash(UUID sourceId, String contentHash);

    List<RawDocumentDto> findBySourceId(UUID sourceId, int limit);

    List<RawDocumentDto> findRecent(int limit);

    boolean deleteById(UUID id);
}
