package it.osint.raven.connectors;

import it.osint.raven.dto.source.RawDocumentDto;
import it.osint.raven.dto.source.SourceDto;

import java.util.List;

public interface SourceConnector {

    List<RawDocumentDto> fetch(SourceDto source);
}
