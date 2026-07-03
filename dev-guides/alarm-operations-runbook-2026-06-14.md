# Alarm Operations Runbook

Data: 2026-06-14

## Scope

Questa nota descrive il comportamento operativo introdotto per la Fase 9 della gestione allarmi.

## Retention

- La retention storica degli allarmi e configurata in runtime configuration tramite `alarms.retentionDays`.
- Il fallback applicativo e `365` giorni.
- Il job `AlarmRetentionService` viene eseguito periodicamente con delay configurabile tramite `velia.alarms.retention.scheduler.fixed-delay-ms`.
- Il valore di default del delay e `3600000` ms.

## Archiviazione Logica

- Il job considera solo allarmi in stato `CLOSED`.
- Un allarme e candidato quando `closedAt` e precedente a `now - retentionDays`.
- Il job non elimina documenti MongoDB.
- Il job valorizza `archivedAt`, aggiorna `updatedAt` e imposta `updatedByActorType = SYSTEM`.
- Ogni archiviazione genera `AlarmEvent.ARCHIVED`.
- Ogni archiviazione genera audit applicativo `ALARM_ARCHIVE` con metadata sicuri.

## Delete Fisico

- Non esiste endpoint pubblico `DELETE /api/alarms`.
- La cancellazione fisica degli allarmi non fa parte del flusso ordinario.
- Un eventuale delete fisico futuro deve essere un job amministrativo dedicato, con approvazione esplicita, audit e possibilmente export preliminare.

## Metriche Operative

- `GET /api/alarms/summary` restituisce conteggi nello scope del caller:
  - totale;
  - attivi;
  - critici;
  - overdue;
  - archiviati logicamente;
  - candidati retention;
  - retention configurata in giorni.

## Query E Indici

- Gli allarmi hanno indice composto su `status`, `closedAt`, `archivedAt` per supportare la selezione dei candidati retention.
- Le query ordinarie restano scoperte dai filtri di scope gia denormalizzati (`tenantUuid`, `organizationUuid`, destinatario/responsabile).

## Verifica Operativa

- Verificare periodicamente che `retention_candidate_count` non cresca in modo anomalo.
- Verificare audit `ALARM_ARCHIVE` in caso di archiviazione automatica.
- Non usare cancellazioni manuali su MongoDB salvo procedura amministrativa approvata.
