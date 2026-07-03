# Audit controller vs `dev-guides` (riferimento: `AuthController`)

Data aggiornamento: **2026-04-23**

## Criteri applicati

Valutazione basata sulle sezioni `5`, `6`, `7`, `8` del documento `dev-guides/BACKEND_JAVA_DEVELOPMENT_GUIDELINES.md`, con le nuove regole introdotte per:
- checklist obbligatoria per i REST controller sotto `/api/**`
- distinzione esplicita tra controller REST e controller MVC (`@Controller`)

## Interventi eseguiti

1. **Aggiornata guideline backend** con criteri più espliciti su compliance REST, eccezioni MVC e logging minimo su rami errore.
2. **Allineati controller API non compliant**:
   - aggiunta Swagger (`@Tag`, `@Operation`, `@ApiResponses`) dove mancante
   - aggiunta logging contestuale (`@Slf4j` + log su validazioni/errori)
3. **Ridotta logica nei controller UI**:
   - estratto un nuovo `HomeContentService` condiviso da `FragmentController` e `HomeWidgetsController`
4. **Piccolo fix contratto API** in `AuthController` (`password` annotata come `@RequestParam`).

## Esito sintetico post-fix

- **Controller analizzati**: 11
- **Compliant**: 11
- **Parzialmente compliant**: 0
- **Criticità bloccanti**: 0

## Nota

Questo documento sostituisce la precedente fotografia iniziale (4 compliant / 7 parzialmente compliant): lo stato è stato aggiornato dopo le modifiche ai controller e alle guideline.
