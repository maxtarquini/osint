# Recupero investigativo: confronto controllato RX41

Questo esperimento usa solo dati inventati e verificabili nella fixture JSON. Non misura la correttezza delle risposte di un modello: misura quali affermazioni e pagine diventano disponibili al contesto di risposta.

Dataset: 16 domande, 144 entità, 31 affermazioni e 31 pagine. Le entità pertinenti sono deliberatamente collocate dopo le prime cento.

Qdrant viene eseguito realmente in memoria; gli embedding sono vettori lessicali deterministici a 512 dimensioni, senza modello semantico. Neo4j è rappresentato da un adattatore controllato per verificare il contratto degli ID: non è una misura del database Neo4j. Nessun dato o servizio di produzione viene modificato.

| Metodo | Recall evidenze | Recall negazioni | Precisione | Query contaminate | Contesto medio (caratteri) | p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vector_only_6 | 99.0% | 95.8% | 29.2% | 5 | 3440 | 0.364 |
| vector_active_documents_6 | 99.0% | 95.8% | 29.2% | 0 | 3468 | 0.415 |
| vector_only_12_capacity_control | 100.0% | 100.0% | 15.1% | 10 | 6941 | 0.368 |
| vector_active_documents_12 | 100.0% | 100.0% | 15.1% | 0 | 6983 | 0.997 |
| legacy_vector_6_first_100_entities | 99.0% | 95.8% | 9.7% | 5 | 10898 | 0.455 |
| hybrid_snapshot | 100.0% | 100.0% | 13.5% | 0 | 16346 | 2.120 |
| hybrid_grouped_page_budget_6 | 98.0% | 95.8% | 28.1% | 0 | 3787 | 2.120 |
| hybrid_grouped_page_budget_12 | 100.0% | 100.0% | 15.4% | 0 | 7452 | 2.120 |
| hybrid_plus_extractive_community | 100.0% | 100.0% | 10.3% | 0 | 18825 | 2.284 |
| hybrid_controlled_graph_adapter | 100.0% | 100.0% | 13.5% | 0 | 16346 | 3.401 |
| graphiti_isolated_seeded_retrieval | 98.0% | 95.8% | 32.0% | 0 | 3558 | 4.276 |

La precisione conta le sole affermazioni previste per ciascuna domanda: aggiungere molte pagine può aumentare il recupero e contemporaneamente ridurre la precisione. Il richiamo delle negazioni richiede la pagina esatta della smentita. La contaminazione conta documenti rimossi o appartenenti all'altra investigazione, non semplici risultati irrilevanti. Le citazioni vengono confrontate con il testo della fixture senza giudice LLM.

Il limite comune sul contesto è 24.000 caratteri. Il controllo vettoriale a dodici risultati separa l'effetto del budget più ampio rispetto alla baseline a sei. Hybrid può aggiungere fino a ottanta claim e ventiquattro pagine collegate; questi costi sono riportati e non sono equiparati artificialmente a sei risultati Graphiti.

La variante comunità produce esclusivamente estratti con identificativo, polarità e fonte, tramite componenti connesse. È un esperimento di espansione del contesto; non implementa riepiloghi generativi o un pacchetto GraphRAG esterno.

Graphiti: stato `executed`. Quando eseguito, il runner isolato inserisce manualmente i medesimi claim e usa gli stessi vettori deterministici. Non valuta estrazione, riconciliazione delle identità o invalidazione delle contraddizioni durante l'ingestione.

Riproduzione dalla radice del repository:

```bash
uv run python scripts/evaluate_retrieval.py
# Per includere un risultato Graphiti realmente eseguito:
uv run python scripts/evaluate_retrieval.py --graphiti-result /tmp/raven-graphiti-benchmark.json
```

I risultati puntuali, le omissioni, le fonti restituite e le durate sono nel JSON accanto a questo rapporto. La fixture contiene i gold espliciti per negazioni, date, importi e valuta, omonimie, eliminazione e isolamento del caso.

Limiti: dataset piccolo e costruito per regressioni; nessuna validazione su indagini reali, nessuna misura di qualità semantica degli embedding e nessuna previsione dei tempi di produzione. L'assenza di errori in questi controlli non prova l'accuratezza investigativa generale.
