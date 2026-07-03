# Notification Routing Email/Webhook Guide

## Obiettivo

Questa guida descrive come configurare e verificare le notifiche email e webhook di Velia senza trasformare i canali esterni in un duplicato rumoroso dell'inbox.

## Canali Disponibili

- In-app: canale persistente principale, abilitato per default sulle categorie consentite.
- Email: canale opzionale, controllato da impostazioni amministrative e preferenze utente.
- Webhook utente: canale opzionale configurato nelle preferenze del singolo utente.
- Webhook routing rule: canale operativo configurato su regole di routing amministrative.

## Configurazione Preferenze Utente

- Ogni categoria ha preferenze separate per in-app, email e webhook.
- La severita minima filtra tutti i canali della categoria.
- Il webhook utente richiede `webhookUrl` quando almeno una categoria abilita `webhookEnabled`.
- Il `webhookSecret` e write-only e non deve mai essere restituito o copiato nei metadata delle notifiche.
- Le categorie nuove o future devono ricevere default espliciti tramite `NotificationPreferenceService`.

## Routing Rule

Usare una routing rule quando una notifica deve:

- assegnare automaticamente un owner;
- inviare webhook/email aggiuntivi a destinatari operativi;
- escalation su notifiche non lette dopo una soglia;
- centralizzare integrazioni esterne per categorie come `SYSTEM`, `ALARM`, `WORKFLOW`, `SECURITY`.

Non usare routing rule per:

- eventi gia coperti da una preferenza utente diretta;
- notifiche CRUD ordinarie;
- retry tecnici transitori;
- payload sensibili o contenuti documento.

## Template

- I template sono definiti per categoria, canale e lingua.
- Lingue supportate: `en`, `it`, `de`; ogni altra lingua deve ricadere su `en`.
- Le variabili consentite includono `event_type` e `metadata.*`.
- I template webhook devono produrre JSON valido.
- I template email devono restare brevi e non includere token, password, segreti, stack trace, prompt o contenuti documento.

## Observability

Il report notifiche deve essere usato per controllare:

- volume per categoria, severita, stato ed event type;
- delivery pending, retrying, failed e dead-letter;
- webhook error rate;
- recipient e organization con volume anomalo;
- eventuale crescita di `SYSTEM` o `WORKFLOW` che segnala rumore operativo.

Quality gate operativo:

- ogni nuova notifica con canali esterni deve avere dedupe stabile;
- ogni nuovo event type deve comparire nei metadata come `eventType`;
- ogni dead-letter webhook/email deve essere investigabile senza esporre payload sensibili;
- testare almeno un render template e un ramo di delivery/routing quando si aggiunge una nuova categoria o un nuovo event type.
