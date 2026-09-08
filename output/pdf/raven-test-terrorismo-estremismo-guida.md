# Prova di catalogazione Raven: scenario RX41

Il PDF `raven-test-terrorismo-estremismo.pdf` contiene otto pagine di testo selezionabile, con nomi ed eventi interamente inventati. È un campione per verificare classificazione, estrazione delle entità, riferimenti fra pagine e riepilogo del documento. Non è una fonte informativa su fatti reali e non è un test OCR per documenti scansionati.

Usa un’indagine di prova con dominio **Terrorism and extremism**, codice `TERRORISM_EXTREMISM`, basato sul dizionario versione 1.0.0 e sulle definizioni ereditate da CORE. Carica soltanto il PDF fra le evidenze. La guida e il file JSON dei risultati attesi devono restare fuori dall’indagine, altrimenti suggerirebbero le risposte all’agente.

Attendi la catalogazione e apri il catalogo del documento. Controlla che mostri otto pagine, un riepilogo complessivo e schede con citazioni pertinenti. Il riepilogo deve conservare la natura fittizia dello scenario, distinguere fatti riferiti e ipotesi, e non trasformare le negazioni in collegamenti positivi.

| Pagina | Contenuto | Verifica principale |
| --- | --- | --- |
| 1 | Identità e attribuzioni | Distinguere organizzazione, affiliata, cellula, gruppo autonomo, rete di reclutamento e atto di designazione. |
| 2 | Pubblicazioni e comunicazione | Distinguere manifesto, pubblicazione, canale, campagne e programma di radicalizzazione. |
| 3 | Cronologia | Separare operazione, attentato e crisi degli ostaggi; non confondere data dell’evento e data del registro. |
| 4 | Luoghi e strutture | Riconoscere campo e rifugio; non inventare coordinate né collocare il rifugio nella città per semplice vicinanza nel testo. |
| 5 | Contrasto e prevenzione | Riconoscere unità e operazione antiterrorismo, oltre al programma di deradicalizzazione; non etichettare il centro civile come estremista. |
| 6 | Movimento economico | Conservare importo e data; nessuna relazione positiva di finanziamento verso le organizzazioni citate nella negazione. |
| 7 | Rettifica e omonimia | Tenere separati partito e affiliata; rispettare l’esclusione dei partiti politici dal sottotipo di gruppo estremista. |
| 8 | Biblioteca | Assegnare EVIDENCE_ONLY; non interpretare un circolo culturale come cellula terroristica. |

> **Categorie ed entità sono informazioni diverse.** Una pagina può avere categoria TEMPORAL perché ricostruisce una cronologia e contenere entità di tipo TER_ATTACK. Il dizionario fornisce 20 sottotipi tematici, tutti rappresentati nel campione. Non definisce categorie di pagina aggiuntive: vengono usate quelle generali del catalogatore.

Il file `raven-test-terrorismo-estremismo-attesi.json` descrive un riferimento manuale, non risultati già prodotti o validati da un modello. Elenca un sottoinsieme delle entità attese e categorie alternative accettabili per le pagine miste. Non richiede formulazioni identiche del riepilogo e non fissa una confidenza numerica. Le citazioni devono comunque comparire nella pagina cui sono attribuite e i codici devono appartenere al dizionario risolto.

Per provare la chat puoi chiedere: «Quale organizzazione è descritta come affiliata e in quale pagina?», «Qual è la differenza tra Ramo Est RX41 e Lista Civica Ramo Est RX41?» e «Esistono prove di finanziamento al Fronte?». Nell’ultima risposta l’agente dovrebbe richiamare la negazione a pagina 6, senza dedurre trasferimenti illeciti. Puoi inoltre chiedere coordinate del rifugio: la risposta corretta è che non sono disponibili.

Questo campione facilita una prima verifica funzionale perché contiene descrizioni esplicite e testo pulito. Un buon risultato non dimostra ancora affidabilità su fonti reali, impaginazioni complesse o scansioni degradate. In questa preparazione sono stati verificati numero di pagine, estrazione del testo, copertura dei 20 sottotipi e impaginazione; non è stato eseguito un test con l’agente collegato a un modello.
