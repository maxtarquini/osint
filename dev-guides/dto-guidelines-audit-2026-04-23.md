# Audit DTO vs `dev-guides` (riferimento: `ProvenanceDto`)

Data aggiornamento: **2026-04-23**

## Baseline di riferimento

È stato usato `src/main/java/com/velia/dto/edt/ProvenanceDto.java` come modello di riferimento per:
- annotazioni Lombok coerenti
- `@JsonIgnoreProperties(ignoreUnknown = true)`
- `@Schema` a livello classe/campo

## Ambito controllo

Controllo focalizzato sui DTO con gap di compliance più evidenti (assenza `@Schema`, stile non omogeneo, assenza resilienza JSON), in particolare:
- `src/main/java/com/velia/dto/UserDTO.java`
- `src/main/java/com/velia/dto/hmi/*`
- `src/main/java/com/velia/dto/llmnodes/NodeDto.java`

## Interventi applicati

1. Aggiornata guideline backend con checklist DTO esplicita.
2. Aggiunte annotazioni `@Schema` a DTO API/document.
3. Uniformato `HmiTelemetryEventDto` allo stile Lombok + `@JsonIgnoreProperties`.
4. Mantenuti i `record` HMI, ma annotati a livello componenti per OpenAPI.

## Esito sintetico post-fix

- DTO aggiornati: **9**
- Gap principali risolti: **documentazione OpenAPI**, **coerenza strutturale**, **resilienza deserializzazione**.
