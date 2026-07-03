# Notification Code Change Plan - 2026-07-02

## Obiettivo

Estendere il meccanismo di notifiche persistenti di Velia in modo controllato, evitando che l'inbox diventi un duplicato dell'audit log.

Le notifiche devono essere generate quando un evento:

- richiede attenzione o azione umana;
- cambia responsabilita o assegnazione;
- segnala un fallimento operativo o asincrono;
- cambia sicurezza, accesso o disponibilita di una risorsa;
- completa un workflow asincrono che l'utente ha esplicitamente avviato.

Ogni fase sotto deve essere confermata prima di procedere alla successiva.

## Stato Attuale Rilevato

Trigger persistenti gia presenti:

- creazione allarme manuale o automatica;
- assegnazione allarme;
- escalation SLA allarme;
- aggiornamento sicurezza account.

Meccanismi gia disponibili:

- `NotificationService` come facade applicativa;
- `NotificationDomainEventNotifier` per eventi di dominio;
- `NotificationCreator` per normalizzazione, template, dedupe, routing, MQTT e delivery;
- categorie esistenti: `ALARM`, `WORKFLOW`, `SECURITY`, `SYSTEM`, `DOCUMENT`, `KB`;
- severita esistenti: `INFO`, `WARNING`, `CRITICAL`;
- risorse collegate esistenti: `ALARM`, `USER`, `ORGANIZATION`, `WORKFLOW`, `DOCUMENT`, `KNOWLEDGE_BASE`, `SYSTEM`;
- routing rule, preferenze utente, template in-app/email/webhook e observability report.

## Principi Di Implementazione

- Non notificare CRUD ordinario se il feedback e gia coperto da toaster o audit.
- Non inserire payload sensibili, prompt, contenuti documento, token, password o stack trace nei metadata.
- Usare `dedupeKey` stabile per eventi ripetibili o scheduler-driven.
- Generare notifiche dal service owner del dominio, non dai controller.
- Mantenere audit e notifiche separati: audit per tracciabilita, inbox per azione.
- Preferire estensioni in `NotificationDomainEventNotifier` o notifier/component dedicati se il file cresce troppo.

## Quando Un Servizio Deve Produrre Notifiche

Ogni service owner deve valutare le notifiche come parte del design di nuove mutazioni, workflow asincroni e policy di sicurezza.
La domanda guida e: "un utente, un profilo organizzazione o un amministratore deve accorgersi di questo evento e forse agire?".

Produrre una notifica persistente quando l'evento:

- richiede attenzione umana o intervento operativo;
- cambia assegnazione, responsabilita, ownership o stato terminale di un lavoro assegnato;
- segnala un fallimento asincrono o operativo non risolto localmente;
- completa con successo un workflow asincrono esplicitamente avviato dall'utente;
- cambia disponibilita, sicurezza, accesso, privilegi o visibilita di una risorsa condivisa;
- supera una soglia di retry, dead-letter, degradazione persistente o errore aggregato;
- interessa una risorsa condivisa e deve essere visibile a un profilo di scope, non solo al chiamante.

Non produrre una notifica persistente quando l'evento:

- e CRUD ordinario senza impatto operativo ulteriore;
- e gia comunicato in modo sufficiente da una risposta HTTP o da un toaster locale;
- e solo audit/tracciabilita senza richiesta di attenzione;
- e un avanzamento intermedio di pipeline, polling, scheduler o job ripetitivo;
- e un login/logout ordinario o una lettura/view senza mutazione rilevante;
- e un errore transitorio gia gestito da retry automatico e non ancora terminale;
- non ha destinatari leggibili o scope chiaro.

Canale corretto per tipo di segnale:

- `UserActivityAuditService`: chi ha fatto cosa, quando, da dove, con quale esito.
- Log applicativi: diagnostica tecnica, stack trace, cause operative e contesto per sviluppatori/operatori.
- MQTT/state sync: aggiornamento live della UI, progress stage e refresh di dashboard.
- Toaster/risposta HTTP: feedback immediato della singola azione sincrona.
- Notifica persistente: attenzione differita, responsabilita, rischio, failure terminale o completamento asincrono atteso.

Regole tecniche obbligatorie:

- La notifica parte dal service owner del dominio o da un componente di dominio invocato dal service; mai direttamente da controller, repository, DTO o frontend.
- La composizione riusabile deve vivere in `com.velia.components.notifications` o in un sotto-package coerente sotto `com.velia.components.<domain>`.
- Il payload deve usare metadata minimi e sicuri: UUID risorsa, categoria, status, request/correlation id, scope e nome file solo quando non sensibile.
- Non inserire mai password, token, prompt, contenuti documento, contenuti generati, stack trace, payload raw o dettagli di errore sensibili.
- Ogni flow deve definire destinatari espliciti: utente richiedente, responsabile/assignee, profilo organization, tenant o administrator.
- Se nessun destinatario e determinabile, la creazione deve essere saltata in modo sicuro.
- Ogni evento ripetibile deve avere `dedupeKey` stabile basata su tipo evento, resource UUID, stato terminale e request/correlation id quando disponibili.
- I test devono coprire creazione, destinatari, metadata safe, dedupe e almeno un ramo in cui la notifica non deve essere prodotta.

## Fase 1 - Allarmi Operativi

Conferma richiesta: SI, prima di implementare.

Scope:

- Aggiungere notifiche per cambio severita verso `HIGH` o `CRITICAL`.
- Aggiungere notifiche per chiusura/risoluzione allarme verso responsabile e/o destinatario.
- Valutare notifica per riapertura o transizione verso stato attivo dopo chiusura, se presente nelle policy.
- Aggiungere notifica per commento su allarme solo quando il commentatore non coincide con il responsabile/destinatario.

File probabili:

- `src/main/java/com/velia/services/AlarmService.java`
- `src/main/java/com/velia/services/NotificationService.java`
- `src/main/java/com/velia/components/notifications/NotificationDomainEventNotifier.java`

Categorie e severita:

- categoria `ALARM`;
- `CRITICAL` per severita allarme `CRITICAL`;
- `WARNING` per allarme `HIGH`, riaperture e commenti su allarmi critici;
- `INFO` per chiusura/risoluzione.

Quality gate:

- Unit test su notifier e service flow interessati.
- Verifica dedupe per evitare duplicati su update ripetuti.
- Nessuna notifica se non ci sono destinatari leggibili.

## Fase 2 - EDT E Workflow Asincroni

Conferma richiesta: SI, dopo completamento Fase 1.

Scope:

- Notificare completamento generazione EDT on-demand al richiedente.
- Notificare fallimento generazione EDT al richiedente e al profilo organizzazione/admin in scope.
- Notificare retry esaurito o dead-letter come evento `WARNING`.
- Evitare notifica persistente per ogni avanzamento stage; quelli restano log/MQTT/dashboard.

File probabili:

- `src/main/java/com/velia/services/EdtTwinGenerationQueueService.java`
- `src/main/java/com/velia/components/edt/EdtRunTrackingComponent.java`
- `src/main/java/com/velia/components/edt/pipelineb/EdtPipelineBTwinGenerationService.java`
- nuovo componente opzionale `src/main/java/com/velia/components/notifications/NotificationWorkflowEventNotifier.java`

Categorie e risorse:

- categoria `WORKFLOW`;
- resource type `WORKFLOW` o `SYSTEM` se non esiste una risorsa piu specifica;
- `actionUrl` verso sezione EDT/digital library.

Quality gate:

- Test per `COMPLETED`, `FAILED`, `RETRY_QUEUED`.
- Metadata limitati a request UUID, correlation ID, organization UUID, stage, status.
- Nessun contenuto generato o documento nei metadata.

## Fase 3 - Documenti E Knowledge Base

Conferma richiesta: SI, dopo completamento Fase 2.

Stato: COMPLETATA il 2026-07-02.

Scope:

- Notificare fallimento enqueue/indexing dei documenti KB.
- Notificare completamento indexing solo per upload/retry esplicitamente avviati dall'utente.
- Notificare fallimenti documenti della digital library organizzazione.
- Notificare eliminazione KB solo se interrompe una risorsa condivisa o fallisce la cancellazione contenuti.

File probabili:

- `src/main/java/com/velia/services/kb/KnowledgeDocumentLifecycleService.java`
- `src/main/java/com/velia/services/kb/KnowledgeBaseService.java`
- `src/main/java/com/velia/components/kb/pipelinec/KbPipelineCDocumentIngestionServiceComponent.java`
- `src/main/java/com/velia/services/OrganizationDocumentLibraryService.java`
- `src/main/java/com/velia/components/organization/OrganizationDocumentPipelineEventPublisher.java`

Categorie e risorse:

- categoria `DOCUMENT` per documenti di organization digital library;
- categoria `KB` per documenti di Knowledge Base;
- resource type `DOCUMENT` o `KNOWLEDGE_BASE`.

Quality gate:

- Dedupe su `documentUuid + terminalStatus + correlationId`.
- Notifiche di successo solo per workflow asincroni user-initiated.
- Fallimenti indirizzati a richiedente, organization scope e/o admin in base alla risorsa.

## Fase 4 - Sicurezza, Account E Accesso

Conferma richiesta: SI, dopo completamento Fase 3.

Stato: COMPLETATA il 2026-07-02.

Scope:

- Integrare notifica per cambio password riuscito.
- Integrare notifica per impersonation riuscita sul target o sugli admin, se policy lo richiede.
- Integrare notifica per creazione account se usata come onboarding.
- Integrare notifica per eliminazione/disabilitazione account verso admin di scope, non verso account eliminato.

File probabili:

- `src/main/java/com/velia/services/AuthService.java`
- `src/main/java/com/velia/services/UsersService.java`
- `src/main/java/com/velia/components/notifications/NotificationDomainEventNotifier.java`

Categorie e severita:

- categoria `SECURITY`;
- `INFO` per cambio password e onboarding;
- `WARNING` per impersonation, disabilitazione, lock o variazioni di accesso rilevanti.

Quality gate:

- Nessun dato segreto nei messaggi o metadata.
- Notifica non generata per login/logout ordinario.
- Notifiche coerenti con audit gia esistente.

## Fase 5 - Sistema, Runtime E Delivery

Conferma richiesta: SI, dopo completamento Fase 4.

Stato: COMPLETATA il 2026-07-02.

Scope:

- Notificare MQTT disconnesso quando e abilitato e il problema persiste oltre una soglia.
- Notificare cambi runtime configuration ad alto impatto: MQTT, retention, alarm SLA, provider AI/Qdrant.
- Notificare fallimenti ripetuti delivery email/webhook agli admin.
- Non notificare ogni singolo errore transitorio.

File probabili:

- `src/main/java/com/velia/services/RuntimeConfigurationService.java`
- `src/main/java/com/velia/services/NotificationDeliveryService.java`
- `src/main/java/com/velia/components/notifications/NotificationDeliveryProcessor.java`
- `src/main/java/com/velia/components/dashboard/AdminDashboardAttentionItemsAssembler.java`

Categorie e severita:

- categoria `SYSTEM`;
- `WARNING` per degradazione persistente;
- `CRITICAL` solo per indisponibilita che blocca workflow core.

Quality gate:

- Soglie e dedupe per eventi scheduler-driven.
- Test su retry/failure aggregation.
- Notifiche solo a profili amministrativi o tenant scope appropriato.

## Fase 6 - Template, Preferenze E Observability

Conferma richiesta: SI, dopo completamento Fase 5.

Stato: COMPLETATA il 2026-07-02.

Scope:

- Rivedere template default per nuove varianti di evento.
- Verificare preferenze per categoria e routing rule.
- Aggiornare eventuali report per distinguere source/event type se necessario.
- Aggiungere documentazione operativa per configurare routing email/webhook.

File probabili:

- `src/main/java/com/velia/components/notifications/NotificationTemplateDefaults.java`
- `src/main/java/com/velia/services/NotificationTemplateService.java`
- `src/main/java/com/velia/services/NotificationObservabilityReportService.java`
- eventuali test notification/report/template.
- `dev-guides/notification-routing-email-webhook-guide.md`

Quality gate:

- Template fallback funzionante per `en`, `it`, `de` dove richiesto dalla UI.
- Report non rompe compatibilita esistente.
- Nessuna regressione sulle preference category.

## Fase 7 - UI Inbox E Microcopy

Conferma richiesta: SI, dopo completamento Fase 6.

Stato: COMPLETATA il 2026-07-02.

Scope:

- Verificare che l'inbox mostri correttamente nuove categorie/severita/action URL.
- Aggiungere eventuali filtri o label solo se necessari.
- Aggiornare traduzioni UI tramite `veliaI18n` per nuove stringhe frontend.
- Evitare nuove stringhe hardcoded nei renderer.

File probabili:

- `src/main/resources/static/js/hmi/domains/notifications/**`
- `src/main/resources/static/js/hmi/core/i18n.js`
- `src/main/resources/templates/home.html`
- `src/main/resources/static/css/notifications-inbox.css`

Quality gate:

- Test JS se cambiano renderer o i18n.
- Verifica responsive e accessibilita.
- Nessun testo sovrapposto o hardcoded monolingua.

## Strategia Di Rollout Consigliata

Ordine consigliato:

1. Allarmi operativi.
2. EDT/workflow asincroni.
3. Documenti/KB.
4. Sicurezza/account.
5. Sistema/runtime/delivery.
6. Template/preferenze/report.
7. UI inbox.

Ogni fase deve produrre una PR o commit separato, con test focalizzati e changelog tecnico breve.

## Decisioni Da Confermare Prima Della Fase 1

- Quali stati allarme sono considerati "risoluzione" nel linguaggio prodotto: `CLOSED`, eventuale `RESOLVED`, o entrambi se presenti.
- Se i commenti allarme devono notificare sempre il responsabile o solo quando l'allarme e `HIGH/CRITICAL`.
- Se i reminder SLA devono restare MQTT-only o diventare notifiche persistenti dopo una soglia.
- Se i destinatari organization-scope devono includere anche profilo `TENANT` per allarmi cross-organization.
