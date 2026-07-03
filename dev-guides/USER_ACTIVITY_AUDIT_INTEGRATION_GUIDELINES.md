# User Activity Audit Integration Guidelines

Questa guida e obbligatoria quando si sviluppano nuove funzioni backend o HMI che modificano dati, accessi, documenti, configurazione o workflow utente in Velia.

## 1) Quando Integrare Audit

Integrare audit quando una funzione:

- autentica o termina sessioni;
- modifica utenti, profili, ruoli o permessi;
- crea, aggiorna o cancella tenant, organizzazioni o utenti organizzazione;
- carica, modifica, ritenta o cancella documenti;
- crea, aggiorna, ritenta o cancella Knowledge Base o documenti KB;
- avvia workflow asincroni, job, code o generazioni EDT;
- modifica runtime configuration, nodi, MQTT, processing o impostazioni HMI operative;
- nega accesso per policy, scope o autorizzazione;
- produce un errore business rilevante per sicurezza o governance.

Non serve audit per:

- pure query read-only senza impatto;
- caricamenti UI senza mutazione;
- health check;
- telemetry tecnica gia coperta da HMI telemetry;
- log diagnostici interni senza azione utente.

Se il dubbio e ragionevole, preferire audit minimale con metadata sicuri.

## 2) Dove Inserire Audit

Inserire audit nel service che possiede il flusso business.

Regole:

- non mettere audit solo nel controller se il service puo essere chiamato da piu endpoint;
- non mettere audit solo nel frontend;
- mantenere il controller sottile;
- passare `UserDTO caller` ai metodi mutativi quando serve identificare actor e scope;
- usare `UserActivityAuditService.recordSafely(...)` per non bloccare il flusso principale;
- registrare eventi dopo il successo della mutazione quando si conosce la risorsa finale;
- registrare eventi `DENIED` prima di rilanciare/ritornare access denied;
- registrare eventi `FAILURE` quando un errore business significativo viene gestito dal service.

## 3) Campi Minimi Obbligatori

Ogni evento deve valorizzare, quando disponibili:

- `actor`: caller autenticato;
- `category`;
- `action`;
- `outcome`;
- `resourceType`;
- `resourceUuid`;
- `resourceLabel`;
- `message`.

Per endpoint HTTP mutativi aggiungere quando utile:

- `httpMethod`;
- `httpPath`;
- `statusCode`;
- `errorCode`;
- `errorMessage`.

Lo scope `tenantUuid` e `organizationUuid` viene derivato dal caller. Usare override nel comando solo quando l'azione riguarda esplicitamente una risorsa in uno scope diverso dal default derivabile dal caller, ad esempio un admin che opera su un tenant specifico.

La consultazione audit deve restare coerente con l'appartenenza dell'actor:

- un caller `TENANT` deve vedere anche eventi il cui `actorUuid` corrisponde a un `UserDTO` con `tenantUuid` nello scope tenant del caller;
- lo scope tenant del caller include `UserDTO.tenantUuid` quando valorizzato e, per compatibilita con dati esistenti, anche `UserDTO.uuid`;
- un caller `ORGANIZATION` deve vedere anche eventi il cui `actorUuid` corrisponde a un `UserDTO` con `organizationUuid` nello scope organization del caller;
- lo scope organization del caller include `UserDTO.organizationUuid` quando valorizzato e, per compatibilita con dati esistenti, anche `UserDTO.uuid`;
- quando si cambia la logica di appartenenza utenti, aggiornare anche `UserActivityAuditQueryService` e relativi test.

## 4) Tassonomia

Usare enum esistenti:

- `AuditCategory`;
- `AuditAction`;
- `AuditOutcome`;
- `AuditResourceType`.

Prima di aggiungere un nuovo valore:

1. verificare che un valore esistente non descriva gia il caso;
2. scegliere un nome stabile, action-oriented e non legato alla UI;
3. aggiornare test e documentazione;
4. considerare filtri UI/API se il nuovo valore deve essere cercabile facilmente.

Naming consigliato per `AuditAction`:

- `<DOMAIN>_CREATE`;
- `<DOMAIN>_UPDATE`;
- `<DOMAIN>_DELETE`;
- `<DOMAIN>_UPLOAD`;
- `<DOMAIN>_RETRY`;
- `<DOMAIN>_REQUEST`;
- `<DOMAIN>_ACCESS_DENIED` solo se serve distinguere da `ACCESS_DENIED` generale.

## 5) Metadata Sicuri

I metadata devono essere piccoli, strutturati e non sensibili.

Ammessi:

- UUID;
- conteggi;
- status;
- flag;
- nome campo modificato senza valore precedente/nuovo se sensibile;
- tipo operazione;
- codici sintetici.

Vietati:

- password;
- token;
- cookie/sessioni;
- prompt e output LLM;
- contenuti documento;
- payload request/response completi;
- segreti runtime;
- stack trace completi;
- dati personali non necessari.

Esempi sicuri:

```java
Map.of(
        "changedFields", List.of("email", "username"),
        "targetProfile", target.getProfile(),
        "documentStatus", savedDocument.getProcessingStatus()
)
```

Esempi non sicuri:

```java
Map.of(
        "password", request.getPassword(),
        "jwt", token,
        "documentText", extractedText,
        "fullPayload", request
)
```

## 6) Pattern Di Implementazione

Pattern base per successo:

```java
userActivityAuditService.recordSafely(UserActivityAuditCommandDto.builder()
        .actor(caller)
        .category(AuditCategory.USER_MANAGEMENT)
        .action(AuditAction.USER_UPDATE)
        .outcome(AuditOutcome.SUCCESS)
        .resourceType(AuditResourceType.USER)
        .resourceUuid(updatedUser.getUuid())
        .resourceLabel(updatedUser.getUsername())
        .message("User updated")
        .metadata(Map.of("changedFields", changedFields))
        .build());
```

Pattern per access denied:

```java
userActivityAuditService.recordSafely(UserActivityAuditCommandDto.builder()
        .actor(caller)
        .category(AuditCategory.ACCESS_CONTROL)
        .action(AuditAction.ACCESS_DENIED)
        .outcome(AuditOutcome.DENIED)
        .resourceType(AuditResourceType.USER)
        .resourceUuid(targetUuid)
        .message("User update denied")
        .errorCode("USER_UPDATE_DENIED")
        .errorMessage("Caller cannot update target user")
        .build());
```

Pattern per failure gestita:

```java
userActivityAuditService.recordSafely(UserActivityAuditCommandDto.builder()
        .actor(caller)
        .category(AuditCategory.DOCUMENT_LIBRARY)
        .action(AuditAction.DOCUMENT_UPLOAD)
        .outcome(AuditOutcome.FAILURE)
        .resourceType(AuditResourceType.ORGANIZATION_DOCUMENT)
        .resourceUuid(documentUuid)
        .message("Document upload failed")
        .errorCode("DOCUMENT_UPLOAD_FAILED")
        .errorMessage(exception.getMessage())
        .build());
```

## 7) Correlation ID

Non generare correlation ID manualmente nei service HTTP standard.

Regole:

- `RequestCorrelationFilter` gestisce `X-Correlation-Id`;
- `UserActivityAuditService` legge `CorrelationIdContext`;
- impostare `correlationId` nel comando solo per processi asincroni o eventi non HTTP che devono propagare un correlation ID noto.

Per workflow asincroni:

- includere il correlation ID nel messaggio/command della coda quando possibile;
- usarlo negli eventi generati dal consumer;
- evitare di perdere il legame tra richiesta iniziale e job successivo.

## 8) Frontend E HMI

La UI non sostituisce l'autorizzazione backend.

Quando si aggiunge una nuova funzione HMI:

- aggiornare sidebar/guard/title solo per navigazione e UX;
- applicare permessi reali sul controller/service;
- non mostrare dati audit fuori scope;
- usare il modulo `Audit & Logs` esistente per consultazione audit;
- se si aggiungono nuove action/category/resource type rilevanti per i filtri, aggiornare `audit-events-shell-renderer.js`;
- aggiungere test JS per guard, sidebar, title o renderer quando cambia la navigazione.

## 9) Test Obbligatori

Per ogni nuova funzione auditata aggiungere o aggiornare test che verifichino:

- evento `SUCCESS` nel caso positivo;
- evento `DENIED` per access denied rilevante;
- evento `FAILURE` per errore business gestito;
- actor e scope corretti;
- category/action/outcome/resource type corretti;
- metadata senza valori sensibili;
- nessuna regressione del risultato business se `recordSafely(...)` fallisce.

Per API di consultazione audit:

- verificare scope per `ADMINISTRATOR`, `TENANT`, `ORGANIZATION`, `USER`;
- verificare filtri nuovi;
- verificare paginazione e ordinamento.

Per UI audit:

- testare API client query params;
- testare rendering tabella/dettaglio;
- testare guard e sidebar quando si cambia disponibilita per profilo.

## 10) Quality Gate Prima Di Chiudere La Feature

Checklist:

- [ ] Ho valutato se la funzione e auditabile.
- [ ] Ho aggiunto evento nel service, non solo nel controller o UI.
- [ ] Ho usato `recordSafely(...)` per i flussi business standard.
- [ ] Ho scelto enum audit esistenti o aggiornato tassonomia e docs.
- [ ] Ho escluso dati sensibili da message/resourceLabel/metadata.
- [ ] Ho coperto success/denied/failure dove applicabile.
- [ ] Ho verificato correlation ID e scope.
- [ ] Ho aggiornato `docs/workflows/user-activity-audit.md` se cambia comportamento audit.
- [ ] Ho aggiornato test Java/JS interessati.
- [ ] Ho eseguito `mvn test` o test mirati motivando eventuali esclusioni.
