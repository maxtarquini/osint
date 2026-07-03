# Audit OpenAPI controller (stato al 2026-07-02)

## Ambito

Verifica di tutti i controller in `src/main/java/com/velia/controllers`, con focus sulla compliance OpenAPI per i soli endpoint REST sotto `/api/**`, come previsto dalle linee guida backend interne (`sezione 5.5` e `sezione 7.4`).

Controller analizzati: **22**
- REST `/api/**`: **20**
- MVC (`@Controller`, non REST): **2** (`HomeController`, `FragmentController`)

## Metodo di verifica

Controlli effettuati via analisi statica del codice:
1. Presenza `@Tag` a livello controller REST.
2. Presenza `@Operation` + `@ApiResponses` su ciascun endpoint mappato (`@GetMapping`, `@PostMapping`, `@PutMapping`, `@PatchMapping`, `@DeleteMapping`).
3. Presenza `@Parameter` per parametri path/query (`@PathVariable`, `@RequestParam`) dove applicabile.
4. Coerenza ambito REST vs MVC con regole interne (Swagger richiesto solo per `/api/**`).

## Risultato sintetico (post-fix)

- Endpoint REST `/api/**` rilevati: **125**
- Endpoint con `@Operation`: **125/125**
- Endpoint con `@ApiResponses`: **125/125**
- Controller REST con `@Tag`: **20/20**

### Esito compliance

- ✅ **Compliant su tagging controller REST** (`@Tag` presente in tutti i 20 controller REST).
- ✅ **Compliant a livello endpoint OpenAPI** (`@Operation`/`@ApiResponses` presenti su tutti gli endpoint REST).
- ✅ **Compliant su distinzione REST/MVC** (i 2 controller MVC non sono soggetti all'obbligo Swagger).

## Dettaglio per controller

### 1) AuthController
- Endpoint: 4
- Stato: compliant su `@Operation`/`@ApiResponses`.
- Parametri: `username`, `password`, `targetUuid` documentati con `@Parameter`.

### 2) EnterpriseDigitalTwinController
- Endpoint: 3
- Stato: compliant su `@Operation`/`@ApiResponses`.
- Parametri: `organizationUuid` documentato con `@Parameter`.

### 3) HmiControlController
- Endpoint: 5
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 4) HmiInterfaceConfigurationController
- Endpoint: 2
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 5) HomeWidgetsController
- Endpoint: 1
- Stato: compliant su `@Operation`/`@ApiResponses`.
- Parametri: `profile` e `section` documentati con `@Parameter`.

### 6) OrganizationDocumentsController
- Endpoint: 8
- Stato: compliant su `@Operation`/`@ApiResponses`.
- Parametri query/path documentati con `@Parameter`.

### 7) OrganizationsController
- Endpoint: 9
- Stato: compliant su `@Operation`/`@ApiResponses`.
- Parametri path documentati con `@Parameter`.

### 8) RuntimeConfigurationController
- Endpoint: 15
- Stato: compliant su `@Operation`/`@ApiResponses`.
- Parametri query documentati con `@Parameter`.

### 9) UsersController
- Endpoint: 6
- Stato: compliant su `@Operation`/`@ApiResponses`.
- Parametri path/query documentati con `@Parameter`.

### 10) AdminDashboardController
- Endpoint: 1
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 11) AlarmsController
- Endpoint: 9
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 12) EnterpriseDigitalTwinChatController
- Endpoint: 7
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 13) KnowledgeBasesController
- Endpoint: 5
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 14) KnowledgeDocumentsController
- Endpoint: 4
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 15) MitreAdminController
- Endpoint: 13
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 16) NotificationsController
- Endpoint: 25
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 17) OrganizationDashboardController
- Endpoint: 1
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 18) TenantDashboardController
- Endpoint: 1
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 19) UserActivityAuditController
- Endpoint: 3
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 20) UserDashboardController
- Endpoint: 1
- Stato: compliant su `@Operation`/`@ApiResponses`.

### 21) FragmentController (MVC)
- Non soggetto a obbligo OpenAPI (fuori da `/api/**`).

### 22) HomeController (MVC)
- Non soggetto a obbligo OpenAPI (fuori da `/api/**`).

## Raccomandazioni operative (priorità)

1. **Bassa priorità**: mantenere sincronizzazione tra response code documentati e gestione errori reali quando evolve la logica applicativa.
2. **Bassa priorità**: standardizzare ulteriormente il livello di dettaglio delle descrizioni `@Parameter` su tutta la codebase.

## Conclusione

Stato complessivo: **compliant OpenAPI**.

La base Swagger è ora uniforme su tutti i controller REST sotto `/api/**`, con copertura completa di:
- annotazioni endpoint (`@Operation`, `@ApiResponses`);
- tagging controller REST (`@Tag`).
