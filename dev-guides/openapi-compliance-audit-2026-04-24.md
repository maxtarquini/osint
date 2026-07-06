# Raven OpenAPI Compliance Audit

## Ambito

Verifica dei controller REST Raven in `src/main/java/it/osint/raven/controllers`, con focus sulla compliance OpenAPI per i soli endpoint REST sotto `/api/**`.

Stato aggiornato: **2026-07-06**.

Controller analizzati: **1**
- REST `/api/**`: **1** (`SystemController`)
- MVC/UI/TUI: **0**

## Metodo di verifica

Controlli effettuati via analisi statica del codice:
1. Presenza `@Tag` a livello controller REST.
2. Presenza `@Operation` + `@ApiResponses` su ciascun endpoint mappato (`@GetMapping`, `@PostMapping`, `@PutMapping`, `@PatchMapping`, `@DeleteMapping`).
3. Presenza `@Schema` su DTO ed enum pubblici esposti dal contratto API.
4. Verifica runtime di `/v3/api-docs` e `/swagger-ui.html`.
5. Presenza dei path e component schemas attesi nel documento OpenAPI generato.

I controlli sono automatizzati in:

```text
src/test/java/it/osint/raven/openapi/OpenApiDocumentationQualityGateTest.java
src/test/java/it/osint/raven/openapi/OpenApiContractTest.java
```

## Risultato sintetico

- Endpoint REST `/api/**` rilevati: **4**
- Endpoint con `@Operation`: **4/4**
- Endpoint con `@ApiResponses`: **4/4**
- Controller REST con `@Tag`: **1/1**
- Swagger UI: **abilitata**
- OpenAPI JSON: **abilitato**

## Endpoint Coperti

- `GET /api/system/info`
- `GET /api/system/configuration`
- `PUT /api/system/configuration`
- `GET /api/system/connections`

## Schemi Coperti

I component schemas includono i DTO di sistema, sorgenti, raw documents, articoli e gli enum pubblici necessari alla generazione di client:

- system: `AppInfo`, `ConnectionProbe`, `ConnectionState`, `ApiErrorResponse`, `EndpointConfigurationDto`, `QdrantConfigurationDto`, `RavenConfigurationDto`
- source: `SourceDto`, `SourceType`, `SourceStatus`, `AuthenticationDto`, `AuthenticationType`, `RawDocumentDto`
- article: `ArticleDto`, `MetadataDto`, `TaxonomyDto`, `EntityDto`, `EntityType`, `RelationshipDto`, `EventDto`, `IntelligenceAssessmentDto`, `AssessmentDto`, `EmbeddingDto`, `ProvenanceDto`, `LinksDto`, `ClaimDto`, `ClaimType`, `Confidence`, `EvidenceDto`, `EvidenceType`

## Raccomandazioni operative (priorità)

1. Aggiornare `OpenApiConfiguration` quando un DTO deve comparire nei components prima di essere referenziato da un endpoint.
2. Aggiornare `OpenApiContractTest` quando vengono aggiunti nuovi path pubblici.
3. Mantenere sincronizzati response code documentati e gestione errori reale.
4. Usare `@Schema(accessMode = WRITE_ONLY)` per segreti e credenziali.

## Conclusione

Stato complessivo: **compliant OpenAPI** per la superficie REST attuale.

La compliance è ora protetta da test automatici e non solo da audit manuale.
