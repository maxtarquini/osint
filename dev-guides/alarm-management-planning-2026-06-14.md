# Alarm Management Planning

Data: 2026-06-14

Questo documento pianifica la gestione allarmi in Velia senza introdurre codice applicativo.
Le decisioni qui raccolte devono guidare la futura implementazione backend, HMI, audit e test.

## 1) Decisioni Confermate

- Gli allarmi hanno severity operativa: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- Gli allarmi hanno un destinatario obbligatorio:
  - utente destinatario;
  - oppure organizzazione destinataria.
- Se il destinatario e una organizzazione, puo essere assegnato un utente del team organizzazione come responsabile della gestione.
- Gli allarmi possono essere generati da:
  - utente tramite API/HMI;
  - backend service;
  - job automatico;
  - workflow futuro.
- Gli SLA usano inizialmente una configurazione globale, non tenant-specific o organization-specific.
- `ADMINISTRATOR` vede tutti gli allarmi.
- `TENANT` vede gli allarmi appartenenti al proprio tenant scope.
- `ORGANIZATION` vede tutti gli allarmi della propria organizzazione.
- `USER` vede gli allarmi destinati a se stesso e gli allarmi assegnati a se stesso come responsabile.
- `USER` non crea allarmi manuali nella prima versione.
- `USER` puo risolvere allarmi assegnati, ma non puo chiuderli.
- Gli allarmi hanno SLA ed escalation.
- Le escalation sono progressive.
- Gli allarmi automatici devono supportare deduplica tramite idempotency key.
- Se una sorgente automatica invia una `idempotencyKey` gia attiva, il nuovo evento viene ignorato e l'allarme esistente non viene duplicato.
- Se una sorgente automatica invia una `idempotencyKey` gia vista ma collegata ad allarme `CLOSED`, viene creato un nuovo allarme con riferimento all'allarme precedente.
- Gli allarmi automatici aggregati mantengono un contatore occorrenze.
- I commenti vengono modellati come eventi `AlarmEvent.COMMENTED`.
- L'escalation deve inviare notifica MQTT e alimentare il pannello messaggi HMI nella top bar.
- I reminder pre-SLA sono previsti con tempo configurabile.
- Tempi di escalation, reminder e retention storico sono configurabili tramite runtime configuration.
- Gli allarmi sono storici e auditabili: non e previsto delete fisico nel flusso ordinario.

## 2) Obiettivi Di Dominio

La feature deve fornire:

- stato corrente dell'allarme;
- timeline storica immutabile delle azioni rilevanti;
- scope denormalizzato per query sicure e performanti;
- policy autorizzative centralizzate nel service;
- supporto nativo a sorgenti automatiche non HTTP;
- base per future notifiche, workflow ed escalation progressive.

## 3) Modello Logico

### Alarm

Rappresenta lo stato corrente dell'allarme.

Campi pianificati:

- `uuid`: identificativo univoco.
- `title`: titolo breve.
- `description`: descrizione operativa.
- `severity`: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- `status`: stato corrente.
- `recipientType`: `USER` oppure `ORGANIZATION`.
- `recipientUserUuid`: valorizzato quando `recipientType = USER`.
- `recipientOrganizationUuid`: valorizzato quando `recipientType = ORGANIZATION`.
- `responsibleUserUuid`: opzionale; solo utenti `USER` appartenenti alla stessa organizzazione dell'allarme.
- `tenantUuid`: scope tenant denormalizzato.
- `organizationUuid`: scope organizzazione denormalizzato quando applicabile.
- `sourceType`: sorgente di creazione.
- `sourceRef`: riferimento opzionale alla sorgente, ad esempio job id, workflow id, resource uuid.
- `sourceName`: nome opzionale del servizio, job o workflow sorgente.
- `idempotencyKey`: chiave opzionale per deduplicare allarmi generati automaticamente.
- `previousAlarmUuid`: riferimento opzionale a un allarme precedente quando un evento automatico riapre il tema dopo una chiusura storica.
- `occurrenceCount`: numero occorrenze aggregate per allarmi automatici deduplicati, default `1`.
- `lastOccurrenceAt`: ultimo istante di occorrenza automatica aggregata.
- `slaDueAt`: scadenza SLA.
- `escalationLevel`: livello escalation corrente, default `0`.
- `escalatedAt`: ultimo istante di escalation.
- `nextEscalationAt`: prossima escalation pianificata, opzionale.
- `nextReminderAt`: prossimo reminder pre-SLA pianificato, opzionale.
- `acknowledgedAt`: istante di presa visione.
- `resolvedAt`: istante di risoluzione.
- `closedAt`: istante di chiusura.
- `createdAt`: istante creazione.
- `updatedAt`: ultimo aggiornamento.
- `createdByActorType`: `USER`, `SYSTEM`, `WORKFLOW`, `BACKEND_SERVICE`.
- `createdByActorUuid`: opzionale per attori utente.
- `updatedByActorType`: opzionale.
- `updatedByActorUuid`: opzionale.
- `metadata`: mappa piccola e non sensibile.

Note:

- `tenantUuid` deve essere sempre valorizzato quando il destinatario permette di ricavarlo.
- `organizationUuid` deve essere valorizzato per allarmi organizzazione e per allarmi destinati a utenti appartenenti a una organizzazione.
- Per compatibilita con pattern esistenti, lo scope organizzazione deve considerare sia `UserDTO.organizationUuid` sia, per profili `ORGANIZATION`, `UserDTO.uuid` dove necessario.
- Per sorgenti automatiche, `idempotencyKey` deve essere valorizzata quando esiste un rischio concreto di generare duplicati per lo stesso evento operativo.
- `sourceType` e obbligatorio; `sourceRef` e `sourceName` restano opzionali ma raccomandati per workflow, job e backend service.
- Se un allarme automatico aperto riceve una occorrenza duplicata, il service puo aggiornare `occurrenceCount` e `lastOccurrenceAt` senza creare un nuovo allarme.
- Se un allarme automatico chiuso riceve una nuova occorrenza con la stessa chiave logica, viene creato un nuovo allarme collegato tramite `previousAlarmUuid`.

### AlarmEvent

Rappresenta lo storico immutabile dell'allarme.

Campi pianificati:

- `uuid`.
- `alarmUuid`.
- `eventType`.
- `actorType`: `USER`, `SYSTEM`, `WORKFLOW`, `BACKEND_SERVICE`.
- `actorUuid`: opzionale.
- `previousStatus`: opzionale.
- `newStatus`: opzionale.
- `previousSeverity`: opzionale.
- `newSeverity`: opzionale.
- `previousResponsibleUserUuid`: opzionale.
- `newResponsibleUserUuid`: opzionale.
- `previousEscalationLevel`: opzionale.
- `newEscalationLevel`: opzionale.
- `note`: testo operativo breve.
- `metadata`: mappa piccola e non sensibile.
- `createdAt`.
- `correlationId`: opzionale, utile per processi asincroni.

## 4) Enum Pianificate

### AlarmSeverity

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

### AlarmStatus

- `OPEN`: allarme creato, non ancora preso in carico.
- `ACKNOWLEDGED`: visto/preso in visione.
- `IN_PROGRESS`: in gestione.
- `RESOLVED`: risolto operativamente.
- `CLOSED`: chiuso/storicizzato.

### AlarmRecipientType

- `USER`
- `ORGANIZATION`

### AlarmSourceType

- `MANUAL`
- `SYSTEM`
- `WORKFLOW`
- `BACKEND_SERVICE`

### AlarmActorType

- `USER`
- `SYSTEM`
- `WORKFLOW`
- `BACKEND_SERVICE`

### AlarmEventType

- `CREATED`
- `ACKNOWLEDGED`
- `ASSIGNED`
- `UNASSIGNED`
- `STATUS_CHANGED`
- `SEVERITY_CHANGED`
- `SLA_UPDATED`
- `ESCALATED`
- `REMINDER_SENT`
- `DUPLICATE_IGNORED`
- `OCCURRENCE_AGGREGATED`
- `RESOLVED`
- `CLOSED`
- `REOPENED`
- `COMMENTED`

## 5) Transizioni Di Stato

Transizioni base consentite:

- `OPEN -> ACKNOWLEDGED`
- `OPEN -> IN_PROGRESS`
- `ACKNOWLEDGED -> IN_PROGRESS`
- `IN_PROGRESS -> RESOLVED`
- `ACKNOWLEDGED -> RESOLVED`
- `OPEN -> RESOLVED`, consentita solo per casi semplici o attori privilegiati.
- `RESOLVED -> CLOSED`
- `RESOLVED -> IN_PROGRESS`, riapertura tecnica prima della chiusura.
- `CLOSED -> OPEN`, riapertura eccezionale, solo `ADMINISTRATOR` o policy dedicata.

Regole:

- `RESOLVED` ferma SLA operativo.
- `CLOSED` ferma definitivamente SLA ed escalation.
- `OPEN`, `ACKNOWLEDGED`, `IN_PROGRESS` mantengono SLA attivo.
- Ogni transizione genera `AlarmEvent`.
- Ogni transizione mutativa rilevante genera anche audit applicativo quando l'attore e utente o quando il processo automatico e governance-relevant.

## 6) Regole Di Visibilita

| Profilo caller | Regola |
| --- | --- |
| `ADMINISTRATOR` | Vede tutti gli allarmi. |
| `TENANT` | Vede allarmi con `tenantUuid` nel proprio tenant scope. Il tenant scope include `caller.uuid` e, per compatibilita, eventuale `caller.tenantUuid` valorizzato. |
| `ORGANIZATION` | Vede allarmi con `organizationUuid` uguale a `caller.organizationUuid` o, per compatibilita legacy, a `caller.uuid`. |
| `USER` | Vede allarmi con `recipientUserUuid = caller.uuid` oppure `responsibleUserUuid = caller.uuid`. |

La UI non deve essere considerata barriera autorizzativa: le stesse regole devono vivere nel service.

## 7) Regole Di Mutazione

| Azione | `ADMINISTRATOR` | `TENANT` | `ORGANIZATION` | `USER` |
| --- | --- | --- | --- | --- |
| Creare allarme manuale | Si, ogni scope | Si, solo proprio tenant | Si, solo propria organizzazione | No, salvo futura policy |
| Creare allarme automatico | Tramite service/system actor | Tramite service/system actor se scoped | Tramite service/system actor se scoped | No |
| Cambiare severity | Si | Si, nel tenant | Si, nella organizzazione | No |
| Assegnare responsabile | Si | Si, a USER della org target nel tenant | Si, a USER del proprio team | No |
| Acknowledge | Si | Si, nel tenant | Si, nella organizzazione | Si, se destinatario o responsabile |
| Impostare in progress | Si | Si, nel tenant | Si, nella organizzazione | Si, se responsabile |
| Risolvere | Si | Si, nel tenant | Si, nella organizzazione | Si, se responsabile |
| Chiudere | Si | Si, nel tenant | Si, nella organizzazione | No |
| Riaprire | Si | Si, nel tenant | Si, nella organizzazione | No |
| Delete fisico | No nel flusso ordinario | No | No | No |

## 8) Validazioni Di Scope

Creazione con destinatario `USER`:

- `recipientUserUuid` e obbligatorio.
- Il target deve esistere.
- Il target deve avere profilo `USER`.
- `tenantUuid` e `organizationUuid` dell'allarme vengono derivati dal target.
- Se `responsibleUserUuid` e valorizzato, deve coincidere con il destinatario oppure appartenere alla stessa organizzazione.

Creazione con destinatario `ORGANIZATION`:

- `recipientOrganizationUuid` e obbligatorio.
- L'organizzazione deve esistere.
- `tenantUuid` e `organizationUuid` dell'allarme vengono derivati dalla organizzazione.
- Se `responsibleUserUuid` e valorizzato, deve essere un profilo `USER` con stessa `organizationUuid`.

Assegnazione responsabile:

- `responsibleUserUuid` deve riferirsi a un `USER`.
- Il responsabile deve appartenere alla stessa `organizationUuid` dell'allarme.
- Se l'allarme non ha `organizationUuid`, l'assegnazione a responsabile organizzativo non e consentita.

## 9) SLA Ed Escalation

Valori iniziali proposti:

| Severity | SLA iniziale |
| --- | --- |
| `LOW` | 5 giorni lavorativi |
| `MEDIUM` | 2 giorni lavorativi |
| `HIGH` | 8 ore lavorative |
| `CRITICAL` | 1 ora |

Regole:

- `slaDueAt` viene calcolato alla creazione.
- Il calendario SLA iniziale e globale.
- Una modifica di severity deve ricalcolare SLA solo se l'allarme non e `RESOLVED` o `CLOSED`.
- L'escalation scatta quando `now > slaDueAt` e lo status e ancora `OPEN`, `ACKNOWLEDGED` o `IN_PROGRESS`.
- L'escalation incrementa `escalationLevel` e valorizza `escalatedAt`.
- Ogni escalation genera `AlarmEvent` di tipo `ESCALATED`.
- Le escalation automatiche devono propagare correlation id se nate da workflow o job.
- La prima versione deve prevedere escalation progressive almeno a livello dati tramite `escalationLevel`.
- I tempi di escalation progressiva sono configurabili tramite runtime configuration.
- Il canale minimo obbligatorio per escalation e:
  - visibilita in UI/API;
  - notifica MQTT;
  - messaggio nel pannello HMI della top bar.
- I reminder pre-SLA sono supportati tramite `nextReminderAt` e tempo configurabile da runtime configuration.

Canali futuri possibili:

- Email.
- Webhook.
- Ulteriori notifiche interne oltre al pannello top bar.

## 10) API Pianificate

Le API REST dovranno seguire le guideline backend:

- controller sottile;
- policy nel service;
- `@Tag`, `@Operation`, `@ApiResponses`;
- DTO con `@Schema`;
- audit nel service owner per flussi mutativi.

Endpoint iniziali:

- `GET /api/alarms`
  - Lista allarmi nello scope del caller.
  - Filtri: `status`, `severity`, `recipientType`, `organizationUuid`, `recipientUserUuid`, `responsibleUserUuid`, `sourceType`, `overdue`, `createdFrom`, `createdTo`.

- `GET /api/alarms/{uuid}`
  - Dettaglio allarme se visibile al caller.

- `GET /api/alarms/{uuid}/events`
  - Timeline dell'allarme se visibile al caller.

- `POST /api/alarms`
  - Creazione manuale.
  - Profili iniziali: `ADMINISTRATOR`, `TENANT`, `ORGANIZATION`.

- `PATCH /api/alarms/{uuid}/assignment`
  - Assegna o rimuove responsabile.

- `PATCH /api/alarms/{uuid}/status`
  - Cambia stato.

- `PATCH /api/alarms/{uuid}/severity`
  - Cambia severity e ricalcola SLA secondo policy.

- `POST /api/alarms/{uuid}/comments`
  - Aggiunge nota storica senza cambiare stato.

Non pianificare `DELETE` pubblico nella prima versione.

API/service automatici:

- Le sorgenti automatiche devono poter inviare `idempotencyKey`.
- A parita di `idempotencyKey` su allarme non chiuso, il service deve evitare duplicati.
- La policy iniziale e ignorare il nuovo evento come allarme duplicato, registrando al massimo un evento tecnico `DUPLICATE_IGNORED`.
- Per allarmi automatici aggregabili, il service puo incrementare `occurrenceCount` e aggiornare `lastOccurrenceAt` senza cambiare destinatario, severity o stato.
- Se l'allarme precedente e `CLOSED`, il service crea un nuovo allarme collegato con `previousAlarmUuid`.

## 11) Service E Componenti Pianificati

Service principali:

- `AlarmService`
  - crea allarmi;
  - aggiorna stato/severity/assignment;
  - scrive `AlarmEvent`;
  - invoca audit applicativo.

- `AlarmQueryService`
  - applica filtri e scope read-only;
  - prepara liste e dettaglio.

- `AlarmAccessPolicy`
  - centralizza visibilita e mutazioni consentite.
  - Puo essere `@Component` sotto `com.velia.components.alarms` se riutilizzato da piu service.

- `AlarmSlaService`
  - calcola `slaDueAt`;
  - valuta overdue;
  - pianifica escalation.

- `AlarmEscalationService`
  - esegue escalation periodiche o event-driven.
  - Deve supportare actor automatico e correlation id.
  - Deve pubblicare notifica MQTT per alimentare il pannello messaggi HMI nella top bar.
  - Deve leggere tempi escalation/reminder dalla runtime configuration.

- `AlarmRuntimeConfigurationService`
  - legge la configurazione globale SLA/escalation/reminder/retention.
  - Fornisce default sicuri se la configurazione non e ancora presente.

Repository pianificati:

- `AlarmRepository`.
- `AlarmEventRepository`.

## 12) Audit Applicativo

Nuovi valori audit da pianificare:

`AuditResourceType`:

- `ALARM`

`AuditAction`:

- `ALARM_CREATE`
- `ALARM_ASSIGN`
- `ALARM_STATUS_UPDATE`
- `ALARM_SEVERITY_UPDATE`
- `ALARM_ESCALATE`
- `ALARM_RESOLVE`
- `ALARM_CLOSE`
- `ALARM_REOPEN`
- `ALARM_COMMENT`

Categoria audit:

- valutare nuovo `AuditCategory.ALARM_MANAGEMENT`;
- in alternativa usare categoria esistente solo se semanticamente adeguata.

Metadata ammessi:

- `severity`;
- `status`;
- `recipientType`;
- `tenantUuid`;
- `organizationUuid`;
- `responsibleUserUuid`;
- `sourceType`;
- `sourceName`;
- `sourceRef`;
- `idempotencyKey`;
- `escalationLevel`;
- `occurrenceCount`;
- `overdue`.

Metadata vietati:

- payload completi;
- stack trace;
- token/sessioni;
- contenuti documentali;
- prompt/output LLM;
- dati personali non necessari.

## 13) HMI Pianificata

La UI deve seguire la single home shell e le regole i18n esistenti.

Vista `ADMINISTRATOR`:

- lista globale;
- filtri tenant, organizzazione, severity, status, overdue;
- dettaglio con timeline;
- azioni complete.

Vista `TENANT`:

- lista tenant scoped;
- filtro organizzazione;
- viste aggregate per SLA e critical;
- gestione allarmi del tenant.

Vista `ORGANIZATION`:

- lista organizzazione;
- assegnazione responsabile dal team;
- gestione operativa degli stati.

Vista `USER`:

- tab "Destinati a me";
- tab "Assegnati a me";
- azioni limitate: acknowledge, in progress, resolve dove consentito.

UI copy:

- tutte le stringhe nuove devono passare da `veliaI18n`;
- supportare `en`, `it`, `de`;
- nessuna autorizzazione reale deve dipendere solo dalla UI.

## 14) Test E Quality Gate

Backend:

- test scope `ADMINISTRATOR`, `TENANT`, `ORGANIZATION`, `USER`;
- test creazione destinatario utente;
- test creazione destinatario organizzazione;
- test responsabile fuori organizzazione negato;
- test transizioni stato consentite/negate;
- test SLA calcolato per severity;
- test escalation su overdue;
- test escalation progressiva;
- test tempi escalation da runtime configuration;
- test reminder pre-SLA da runtime configuration;
- test deduplica tramite `idempotencyKey` per sorgenti automatiche;
- test nuovo allarme collegato quando una occorrenza arriva dopo `CLOSED`;
- test incremento `occurrenceCount` dove previsto;
- test notifica MQTT per escalation;
- test storico `AlarmEvent`;
- test commento come `AlarmEvent.COMMENTED`;
- test audit `SUCCESS`, `DENIED`, `FAILURE` dove applicabile;
- test metadata audit senza dati sensibili.

Frontend:

- test API client query params;
- test renderer lista/dettaglio/timeline;
- test i18n almeno inglese e italiano;
- test visibilita azioni per profilo;
- test pannello messaggi HMI top bar alimentato da escalation/notifiche;
- test stati vuoti, errore, loading.

OpenAPI:

- controller `/api/**` con Swagger completo;
- DTO request/response con `@Schema`;
- response codes coerenti con comportamento reale.

## 15) Piano Di Implementazione Per Fasi

### Fase 0 - Preparazione Contratti

Obiettivo:

- fissare il contratto tecnico prima di introdurre logica runtime.

Attivita:

- definire enum:
  - `AlarmSeverity`;
  - `AlarmStatus`;
  - `AlarmRecipientType`;
  - `AlarmSourceType`;
  - `AlarmActorType`;
  - `AlarmEventType`.
- definire DTO persistence:
  - `AlarmDto`;
  - `AlarmEventDto`.
- definire DTO API request/response:
  - create alarm;
  - update status;
  - update assignment;
  - update severity;
  - add comment;
  - list/search response;
  - detail response.
- aggiungere annotazioni Swagger e JSON secondo guideline DTO.
- definire repository e indici.

Repository indexes minimi:

- `tenantUuid`;
- `organizationUuid`;
- `recipientUserUuid`;
- `responsibleUserUuid`;
- `status`;
- `severity`;
- `slaDueAt`;
- `idempotencyKey`;
- `previousAlarmUuid`;
- `createdAt`.

Quality gate:

- DTO compilano;
- repository avviabili;
- nessuna logica business ancora esposta;
- test base su serializzazione/default DTO dove utile.

### Fase 1 - Policy, Scope E Validazioni

Obiettivo:

- rendere corretta la visibilita prima di esporre API.

Attivita:

- implementare `AlarmAccessPolicy`.
- implementare risoluzione scope per:
  - `ADMINISTRATOR`;
  - `TENANT`;
  - `ORGANIZATION`;
  - `USER`.
- gestire compatibilita legacy organization:
  - `caller.organizationUuid`;
  - `caller.uuid` per profilo `ORGANIZATION`.
- validare destinatario utente.
- validare destinatario organizzazione.
- validare responsabile appartenente alla stessa organizzazione.

Quality gate:

- test scope per tutti i profili;
- test access denied su cross-tenant e cross-organization;
- test `USER` vede solo destinatario/responsabile;
- test responsabile fuori organizzazione negato.

### Fase 2 - Core Service E Storico

Obiettivo:

- creare e modificare allarmi mantenendo timeline immutabile.

Attivita:

- implementare `AlarmService`.
- implementare creazione allarme manuale.
- implementare creazione allarme da attore automatico.
- implementare transizioni stato.
- implementare assegnazione responsabile.
- implementare cambio severity.
- implementare commenti come `AlarmEvent.COMMENTED`.
- scrivere `AlarmEvent` per ogni mutazione rilevante.
- impedire delete fisico pubblico.

Quality gate:

- test creazione destinatario `USER`;
- test creazione destinatario `ORGANIZATION`;
- test transizioni consentite/negate;
- test eventi storici creati correttamente;
- test `USER` puo risolvere se responsabile ma non chiudere;
- test `ADMINISTRATOR`, `TENANT`, `ORGANIZATION` chiudono nel proprio scope.

### Fase 3 - SLA, Runtime Configuration E Reminder

Obiettivo:

- introdurre SLA globale configurabile e reminder pre-SLA.

Attivita:

- implementare `AlarmRuntimeConfigurationService`.
- definire default globali:
  - `LOW`: 5 giorni lavorativi;
  - `MEDIUM`: 2 giorni lavorativi;
  - `HIGH`: 8 ore lavorative;
  - `CRITICAL`: 1 ora.
- implementare `AlarmSlaService`.
- calcolare `slaDueAt` alla creazione.
- ricalcolare SLA su cambio severity se status non e `RESOLVED`/`CLOSED`.
- gestire `nextReminderAt`.
- leggere tempi reminder da runtime configuration.

Quality gate:

- test SLA per severity;
- test ricalcolo SLA su cambio severity;
- test SLA fermo su `RESOLVED`/`CLOSED`;
- test reminder pre-SLA configurabile;
- test default runtime configuration quando manca configurazione esplicita.

### Fase 4 - Idempotency E Aggregazione Automatica

Obiettivo:

- evitare duplicati da backend/workflow e tracciare occorrenze ricorrenti.

Attivita:

- implementare deduplica su `idempotencyKey`.
- se allarme non chiuso:
  - non creare nuovo allarme;
  - registrare al massimo `AlarmEvent.DUPLICATE_IGNORED`;
  - per allarmi aggregabili, incrementare `occurrenceCount` e aggiornare `lastOccurrenceAt`.
- se allarme `CLOSED`:
  - creare nuovo allarme;
  - valorizzare `previousAlarmUuid`.
- gestire `sourceType` obbligatorio.
- valorizzare `sourceRef` e `sourceName` quando disponibili.

Quality gate:

- test duplicato ignorato su allarme aperto;
- test aggregazione occorrenze;
- test nuovo allarme collegato su precedente `CLOSED`;
- test source metadata sicuri;
- test indice/query per `idempotencyKey`.

### Fase 5 - Audit Applicativo

Obiettivo:

- rendere la feature storica e governance-ready.

Attivita:

- aggiungere tassonomia audit:
  - `AuditResourceType.ALARM`;
  - azioni `ALARM_*`.
- valutare `AuditCategory.ALARM_MANAGEMENT`.
- registrare audit nel service owner.
- coprire:
  - success;
  - denied;
  - failure business gestite.
- mantenere metadata piccoli e non sensibili.

Quality gate:

- test audit `SUCCESS`;
- test audit `DENIED`;
- test audit `FAILURE` dove applicabile;
- test scope audit corretto;
- test nessun dato sensibile in metadata.

### Fase 6 - API REST

Obiettivo:

- esporre il dominio allarmi in modo coerente con le guideline backend.

Attivita:

- implementare `AlarmsController`.
- endpoint:
  - `GET /api/alarms`;
  - `GET /api/alarms/{uuid}`;
  - `GET /api/alarms/{uuid}/events`;
  - `POST /api/alarms`;
  - `PATCH /api/alarms/{uuid}/assignment`;
  - `PATCH /api/alarms/{uuid}/status`;
  - `PATCH /api/alarms/{uuid}/severity`;
  - `POST /api/alarms/{uuid}/comments`.
- aggiungere Swagger completo.
- mappare status code coerenti.
- mantenere controller sottile.

Quality gate:

- test controller per profili e scope;
- test response code;
- test OpenAPI annotations;
- test filtri lista principali.

### Fase 7 - Escalation Job, MQTT E Top Bar HMI

Obiettivo:

- rendere operativa l'escalation e visibile la notifica.

Attivita:

- implementare `AlarmEscalationService`.
- implementare job o trigger periodico escalation.
- leggere tempi escalation da runtime configuration.
- incrementare `escalationLevel`.
- generare `AlarmEvent.ESCALATED`.
- pubblicare notifica MQTT.
- alimentare pannello messaggi HMI nella top bar.
- gestire reminder pre-SLA via MQTT/HMI se previsto dalla configurazione.

Quality gate:

- test escalation su overdue;
- test escalation progressiva;
- test MQTT publish;
- test messaggio HMI top bar;
- test reminder pre-SLA;
- test nessuna escalation per `RESOLVED`/`CLOSED`.

### Fase 8 - HMI Allarmi Per Profilo

Obiettivo:

- fornire esperienza operativa distinta per profilo.

Attivita:

- aggiungere sezione allarmi nella home shell.
- vista `ADMINISTRATOR`:
  - lista globale;
  - filtri tenant/organization/severity/status/overdue;
  - dettaglio e timeline.
- vista `TENANT`:
  - lista tenant scoped;
  - filtro organizzazione;
  - overview critical/SLA.
- vista `ORGANIZATION`:
  - lista organizzazione;
  - assegnazione responsabile team;
  - gestione stati.
- vista `USER`:
  - tab "Destinati a me";
  - tab "Assegnati a me";
  - azioni limitate.
- aggiornare `veliaI18n` per `en`, `it`, `de`.

Quality gate:

- test renderer stati loading/empty/error;
- test azioni per profilo;
- test i18n;
- test responsive;
- verifica che la UI non sostituisca autorizzazione backend.

### Fase 9 - Retention E Operativita

Obiettivo:

- completare gestione storica configurabile e manutenzione operativa.

Attivita:

- aggiungere runtime configuration per retention.
- definire comportamento:
  - archiviazione logica;
  - export futuro;
  - cancellazione fisica solo con job amministrativo dedicato, se approvato.
- aggiungere metriche o conteggi utili a dashboard.
- documentare procedure operative.

Quality gate:

- test configurazione retention;
- test nessun delete fisico pubblico;
- test query storico performanti;
- documentazione aggiornata.

### Fase 10 - Hardening Finale

Obiettivo:

- chiudere regressioni e preparare merge.

Attivita:

- eseguire test backend completi.
- eseguire test frontend rilevanti.
- verificare OpenAPI.
- verificare audit UI/API.
- verificare runtime configuration fallback.
- verificare messaggi MQTT/HMI.
- aggiornare documentazione finale.

Quality gate:

- build verde;
- test principali verdi;
- nessuna regressione scope/autorizzazione;
- nessun dato sensibile in log/audit/metadata;
- documento planning aggiornato con eventuali deviazioni approvate.

## 16) Decisioni Chiuse Per La Prima Versione

- Calendario SLA globale.
- Nessuna creazione manuale da profilo `USER`.
- `USER` puo risolvere allarmi assegnati ma non chiuderli.
- `ADMINISTRATOR`, `TENANT` e `ORGANIZATION` possono chiudere allarmi nel proprio scope.
- Canale escalation minimo: UI/API.
- Canali escalation prima versione: UI/API, MQTT, pannello messaggi HMI nella top bar.
- Escalation progressive supportate tramite `escalationLevel`.
- Tempi escalation progressiva configurabili tramite runtime configuration.
- Reminder pre-SLA previsti con tempo configurabile tramite runtime configuration.
- Deduplica allarmi automatici tramite `idempotencyKey`.
- Duplicato automatico su allarme non chiuso: ignorare il nuovo evento o aggregare occorrenza senza duplicare allarme.
- Nuova occorrenza automatica su allarme `CLOSED`: creare nuovo allarme collegato al precedente.
- Allarmi automatici aggregabili con `occurrenceCount`.
- Ownership sorgenti automatiche: `sourceType` obbligatorio, `sourceRef` e `sourceName` opzionali ma raccomandati.
- Commenti modellati come `AlarmEvent.COMMENTED`.
- Retention storico configurabile tramite runtime configuration.

## 17) Stato Implementazione Prima Versione

Aggiornamento Fase 10, 2026-06-14:

- Fasi 0-2 completate: modello dominio, policy autorizzative, core service e timeline `AlarmEvent`.
- Fase 3 completata: runtime configuration per SLA, reminder, escalation e retention.
- Fase 4 completata: deduplica allarmi automatici tramite `idempotencyKey`, contatore occorrenze e collegamento a storico chiuso.
- Fase 5 completata: audit applicativo per flussi allarme `SUCCESS`, `DENIED` e `FAILURE` dove applicabile.
- Fase 6 completata: API REST scoped per lista, dettaglio, timeline, mutazioni operative e configurazione allarmi.
- Fase 7 completata: job escalation/reminder, eventi MQTT `ALARM_ESCALATED` e `ALARM_REMINDER`, integrazione pannello messaggi HMI.
- Fase 8 completata: HMI allarmi per profilo con filtri, KPI, dettaglio, timeline, assegnazione, status update e commenti.
- Fase 9 completata: retention operativa tramite archiviazione logica, `ALARM_ARCHIVE`, metriche scoped e runbook operativo.
- Fase 10 completata: hardening finale, verifica test, OpenAPI, audit UI/API, runtime fallback e messaggistica MQTT/HMI.

Deviazioni approvate o scelte operative:

- La retention non elimina fisicamente gli allarmi: valorizza `archivedAt` e conserva timeline/audit.
- I job schedulati hanno `initialDelay` configurabile per evitare mutazioni immediate all'avvio applicativo.
- Il pannello HMI allarmi usa le API backend gia autorizzate; i controlli frontend sono ergonomici e non sostituiscono la policy server-side.
- La creazione manuale da HMI non e inclusa nella prima versione operativa; le API la supportano per profili autorizzati.

Quality gate eseguiti:

- `find src/main/resources/static/js/hmi -type f -name '*.js' -print0 | xargs -0 -n1 node --check`
- `git diff --check`
- `mvn test`
- Avvio applicazione locale e verifica `/v3/api-docs` per endpoint allarmi, summary, `archived` e campi retention.

## 18) Decisioni Ancora Aperte

- Numero di livelli escalation e destinatari per ciascun livello.
- Eventuale configurazione futura SLA per tenant o organizzazione.
- Se aggiungere email/webhook come canali notifica oltre MQTT/HMI.
- Schema esatto delle chiavi runtime configuration per escalation, reminder e retention.
