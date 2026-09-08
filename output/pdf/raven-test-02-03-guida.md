# RX41: prova con più documenti

I due PDF continuano lo scenario interamente inventato del primo fascicolo. Il Documento 2, datato 1 marzo 2026, contiene cinque pagine di connessioni aggiuntive; il Documento 3, datato 5 marzo 2026, contiene cinque pagine di smentite, rettifiche e aggiornamenti. Entrambi hanno testo selezionabile. Non sono scansioni da usare per una prova OCR.

Carica i PDF nella stessa indagine del primo documento, con dominio **Terrorism and extremism** (`TERRORISM_EXTREMISM`). Per osservare come cambiano i risultati, completa prima il catalogo del Documento 1, aggiungi il Documento 2 e annota le connessioni prodotte. Solo dopo aggiungi il Documento 3 e confronta le risposte e il grafo ottenuti. Distingui sempre il riepilogo del catalogo dal grafo: sono elaborazioni differenti e il caricamento non dimostra che tutte le viste siano state ricalcolate.

**Non caricare questa guida o il JSON dei risultati attesi fra le evidenze.** Servono al revisore e suggerirebbero le risposte all’agente. I risultati elencati sono aspettative manuali: non è stata eseguita la classificazione con il modello collegato a Raven.

## Le domande da usare

1. Quali collegamenti aggiunge Unione Levante RX41 alla rete descritta nel primo documento? Qual è la fonte originaria di ciascuno?
2. Chi pubblica e chi diffonde Bollettino Ceneri RX41? Queste relazioni vengono smentite dal terzo documento?
3. Quali fonti sostengono o negano la dipendenza di Cerchio Grigio RX41 da Ramo Est RX41? È possibile risolvere il conflitto con i documenti disponibili?
4. Canale Prisma RX41 e Laboratorio Prisma RX41 sono lo stesso soggetto? Quale autore ritira l’ipotesi e quando?
5. Quanti versamenti distinti di 240 euro sono documentati? Quali affermazioni sul presunto trasferimento successivo restano contestate?
6. Qual è la data dell’Attacco di Piazza Lume RX41 dopo la rettifica? Chi ha corretto la fonte e quale evento resta datato 11 febbraio?
7. Dove si trova Casa Nebbia RX41? Il ritiro di Valle Torva RX41 permette di assegnarle un’altra localizzazione?
8. La smentita di Unità Tutela RX41 dimostra che Nucleo Bruma RX41 sia estraneo all’attacco, oppure ridimensiona soltanto una precedente attribuzione?
9. Il Laboratorio collaborava con il Centro al 1 marzo 2026? E al 5 marzo? Quale collaborazione civile prosegue?
10. Per ogni risposta, indica documento, pagina, affermazione e natura della fonte: originaria, trascritta, anonima, parte interessata o autore della rettifica.

## Come devono evolvere le interpretazioni

| Affermazione nel Documento 2 | Riscontro nel Documento 3 | Interpretazione da verificare |
| --- | --- | --- |
| A2-01, p. 1: affiliazione e collaborazione di Unione Levante RX41 | N3-02, p. 1 | Attribuzione invariata; nessuna nuova conferma indipendente. |
| A2-02, p. 1: Cerchio Grigio RX41 dipenderebbe da Ramo Est RX41 | N3-01, p. 1 | Fonte anonima contro smentita di parte: conflitto ancora aperto. |
| A2-03, p. 2: relazioni editoriali | N3-04, p. 2 | Non ritirate. La trascrizione di CE-03 non è una seconda fonte indipendente. |
| A2-04, p. 2: possibile identità fra Canale e Laboratorio Prisma RX41 | N3-03, p. 2 | Ipotesi ritirata dal suo autore; identità separate. |
| A2-05, p. 3: presunto trasferimento successivo dei 240 euro | N3-05, p. 3 | Smentita circoscritta del beneficiario, senza verifica indipendente; niente finanziamento accertato. |
| A2-06, p. 3: possibile uso del contributo per Programma Ritorno RX41 | N3-06, p. 3 | Non determinato: la ricevuta priva del nome non prova né esclude la destinazione. |
| A2-07, p. 4: attentato datato 11 febbraio | N3-07, p. 4 | L’autore corregge in 10 febbraio; mantenere la storia della rettifica. |
| A2-08, p. 4: rifugio a Valle Torva RX41 | N3-08, p. 4 | Localizzazione ritirata; posizione sconosciuta, nessuna coordinata alternativa. |
| A2-09, p. 4: responsabilità accertata del Nucleo | N3-09, p. 4 | Espressione ritirata; resta un’ipotesi non confermata, non una prova di estraneità. |
| A2-10, p. 5: collaborazione educativa della Biblioteca | N3-11, p. 5 | Dichiarata ancora attiva al 5 marzo 2026. |
| A2-11, p. 5: supporto grafico del Laboratorio | N3-10, p. 5 | Attivo dal 21 febbraio al 2 marzo inclusi; cessato dal 3 marzo. Le due fonti sono temporalmente compatibili. |

> **Confidenza nell’estrazione e attendibilità della fonte.** Una frase fittizia o una smentita interessata possono essere estratte correttamente con elevata certezza testuale. Questo non ne rende vero il contenuto nel mondo reale e non risolve un conflitto fra fonti. Valuta separatamente la correttezza della citazione, il tipo di affermazione e il suo supporto.

> **Negazioni pertinenti al dominio.** Le pagine del Documento 3 restano rilevanti per l’indagine anche quando negano un rapporto. Non devono diventare automaticamente EVIDENCE_ONLY soltanto perché contengono negazioni. Le categorie generali plausibili sono IDENTITY/RELATIONSHIPS/NARRATIVE per le prime due pagine, FINANCIAL per la terza e TEMPORAL/GEOGRAPHIC/RELATIONSHIPS per le ultime; nelle pagine miste è accettabile una scelta diversa se motivata dal contenuto.

Le entità del primo fascicolo devono conservare i loro nomi completi. Unione Levante RX41 è un nuovo candidato `TER_AFFILIATE`; Laboratorio Prisma RX41 è un’organizzazione civile, non un alias del `TER_MEDIA_CHANNEL` Canale Prisma RX41. Cellula Verde RX41 rimane un circolo culturale e Lista Civica Ramo Est RX41 rimane il partito distinto dall’affiliata Ramo Est RX41.

Il file `raven-test-02-03-attesi.json` contiene gli 11 abbinamenti fra affermazione e riscontro, le pagine fisiche e gli hash SHA-256 dei PDF finali. I codici A2 e N3 sono identificativi delle affermazioni, non istruzioni all’agente. Le fonti interne citate sono parte della narrazione sintetica: quando il testo ne riporta soltanto una trascrizione o un estratto, non vanno contate come ulteriori allegati caricati né come verifiche indipendenti.
