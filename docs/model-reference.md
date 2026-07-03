# Model Reference

## SourceDto

Represents an operational OSINT source.

Collection: `sources`

Key fields:

- `id`
- `name`
- `type`
- `endpoint`
- `description`
- `status`
- `priority`
- `polling_interval`
- `last_successful_run`
- `last_execution`
- `last_content_timestamp`
- `authentication`
- `configuration`
- `tags`

Supported source types:

- `WEBSITE`
- `RSS`
- `SITEMAP`
- `TELEGRAM`
- `X`
- `FACEBOOK`
- `YOUTUBE`
- `PDF`
- `EMAIL`
- `API`
- `FILESYSTEM`
- `DATABASE`
- `MANUAL`
- `DISCORD`
- `MASTODON`
- `BLUESKY`
- `REDDIT`
- `DARK_WEB`
- `TOR`
- `RSS_CUSTOM`

## AuthenticationDto

Represents source access credentials.

Fields:

- `type`
- `username`
- `password`
- `api_key`
- `bearer_token`

Supported authentication types:

- `NONE`
- `BASIC`
- `API_KEY`
- `BEARER_TOKEN`
- `OAUTH2`
- `SESSION_COOKIE`
- `CUSTOM`

Security rule:

Authentication values must be treated as sensitive and excluded from logs and normal UI diagnostics.

## RawDocumentDto

Represents acquired raw content, independent of source type.

Collection: `raw_documents`

Fields:

- `id`
- `source_id`
- `original_uri`
- `acquisition_time`
- `content_timestamp`
- `mime_type`
- `raw_content`
- `content_hash`
- `metadata`

Examples of raw content:

- HTML page
- RSS item content
- Telegram message payload
- PDF bytes
- email body
- REST JSON response
- local filesystem document

## ArticleDto

Represents a structured intelligence article derived from a raw document.

Collection: `articles`

Top-level fields:

- `id`
- `raw_document_id`
- `metadata`
- `taxonomy`
- `entities`
- `relationships`
- `events`
- `intelligence_assessment`
- `assessment`
- `embedding`
- `provenance`
- `links`
- `claims`

Important boundary:

`ArticleDto` does not contain source details. Source traceability goes through `raw_document_id -> RawDocumentDto.source_id -> SourceDto.id`.

## Article Enrichment Levels

`MetadataDto`

- `title`
- `subtitle`
- `author`
- `publication_date`
- `category`
- `tags`
- `images`
- `attachments`

`TaxonomyDto`

- `domain`
- `sub_domain`
- `event_type`
- `sector`
- `impact_level`
- `topics`
- `keywords`

`EntityDto`

- `id`
- `type`
- `name`
- `normalized_name`
- `wikidata_id`
- `confidence`

`RelationshipDto`

- `source`
- `target`
- `predicate`
- `confidence`

`EventDto`

- `id`
- `type`
- `date`
- `description`
- `participants`
- `locations`

`ClaimDto`

- `id`
- `source_entity_id`
- `statement`
- `target_entity_ids`
- `date`
- `type`
- `confidence`
- `evidence`

`EvidenceDto`

- `id`
- `type`
- `source`
- `url`
- `excerpt`
- `locator`
- `confidence`

## Mongo Indexes

`sources`

- unique sparse `name`
- `type + endpoint`
- `status + priority`
- `tags`

`raw_documents`

- unique sparse `source_id + original_uri`
- unique sparse `source_id + content_hash`
- `acquisition_time`
- `content_timestamp`
- `mime_type`

`articles`

- unique sparse `raw_document_id`
- `metadata.publication_date`
- `taxonomy.domain + taxonomy.sub_domain + taxonomy.event_type`
- `entities.normalized_name + entities.type`
- `events.type + events.date`

## JSON Contract

DTO fields exposed to JSON and Mongo payloads use `snake_case`.

Examples:

- `polling_interval`
- `last_successful_run`
- `source_id`
- `raw_document_id`
- `publication_date`
- `impact_level`
- `normalized_name`
- `source_entity_id`
- `target_entity_ids`
- `extraction_time`
