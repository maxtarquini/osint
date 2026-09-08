# Recupero investigativo: confronto controllato RX41

Questo esperimento usa solo dati inventati e verificabili nella fixture JSON. Non misura la correttezza delle risposte di un modello: misura quali affermazioni e pagine diventano disponibili al contesto di risposta.

Dataset: 16 domande, 144 entità, 31 affermazioni e 31 pagine. Le entità pertinenti sono deliberatamente collocate dopo le prime cento.
Il controllo modeled_first_100 simula un taglio dei candidati e delle loro affermazioni: non riproduce alla lettera il vecchio formato dei prompt. La fixture è stata usata durante lo sviluppo delle modifiche; non è un test indipendente.

Qdrant viene eseguito realmente in memoria; gli embedding sono vettori lessicali deterministici a 512 dimensioni, senza modello semantico. Neo4j è rappresentato da un adattatore controllato per verificare il contratto degli ID: non è una misura del database Neo4j. Nessun dato o servizio di produzione viene modificato.

| Metodo | Recall evidenze | Recall negazioni | Precisione | Contaminazioni | Pagine medie | Contesto medio (caratteri) | p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vector_only_6 | 99.0% | 95.8% | 29.2% | 5 | 6 | 3440 | 0.325 |
| vector_active_documents_6 | 99.0% | 95.8% | 29.2% | 0 | 6 | 3468 | 0.378 |
| vector_only_12_capacity_control | 100.0% | 100.0% | 15.1% | 10 | 12 | 6941 | 0.337 |
| vector_active_documents_12 | 100.0% | 100.0% | 15.1% | 0 | 12 | 6983 | 0.407 |
| modeled_vector_6_first_100_cutoff_control | 99.0% | 95.8% | 9.7% | 5 | 18 | 10898 | 0.312 |
| hybrid_snapshot | 100.0% | 100.0% | 14.4% | 0 | 12.62 | 15273 | 1.639 |
| hybrid_grouped_page_budget_6 | 98.0% | 95.8% | 28.1% | 0 | 6 | 3787 | 1.639 |
| hybrid_grouped_page_budget_12 | 100.0% | 100.0% | 15.4% | 0 | 11.81 | 7452 | 1.639 |
| hybrid_plus_extractive_community | 100.0% | 100.0% | 10.4% | 0 | 17.44 | 18217 | 1.738 |
| hybrid_controlled_graph_adapter | 100.0% | 100.0% | 14.4% | 0 | 12.56 | 15234 | 2.367 |
| graphiti_isolated_seeded_retrieval | 98.0% | 95.8% | 32.0% | 0 | 5.62 | 3558 | 4.276 |

La precisione conta le sole affermazioni previste per ciascuna domanda: aggiungere molte pagine può aumentare il recupero e contemporaneamente ridurre la precisione. Il richiamo delle negazioni richiede la pagina esatta della smentita. La contaminazione conta documenti rimossi o appartenenti all'altra investigazione, non semplici risultati irrilevanti. Le citazioni vengono confrontate con il testo della fixture senza giudice LLM.
I valori sono medie per domanda: il recall esclude i due controlli senza risultati attesi, mentre la precisione comprende tutte le sedici domande. Una domanda ampia con sette fonti pesa quanto una domanda locale con una fonte.

Separazione fra ranking e robustezza: i punti dei documenti rimossi vengono lasciati nell'indice appositamente per simulare una cancellazione incompleta. Una sincronizzazione ordinaria riuscita li rimuoverebbe. Le varianti vector_active_documents filtrano prima della ricerca gli stessi documenti visibili a Hybrid e Graphiti: servono al confronto di ranking su corpus uguale. Il filtro del caso mantiene sempre fuori i punti dell'altra investigazione.
Nei due controlli senza evidenze pertinenti (documento rimosso e altro caso), l'assenza di contaminazione non equivale a un'astensione: possono ancora essere restituite pagine irrilevanti. Il JSON riporta anche questi casi. Il comportamento della risposta finale del modello non viene misurato.

Il limite comune sul contesto è 24.000 caratteri. Il controllo vettoriale a dodici risultati separa l'effetto del budget più ampio rispetto alla baseline a sei. Hybrid parte da dodici claim ordinati e può includere fino a ottanta claim attraverso i confronti, oltre a ventiquattro pagine collegate; questi costi sono riportati e non sono equiparati artificialmente a sei risultati Graphiti.
I controlli hybrid_grouped_page_budget limitano a sei o dodici pagine dopo il recupero, preservando gruppi interi di affermazione/smentita. La loro latenza resta quella del recupero Hybrid completo. Tutte le durate sono mediane di tre campioni consecutivi per domanda; non includono l'indicizzazione iniziale.

La variante comunità produce esclusivamente estratti con identificativo, polarità e fonte, tramite componenti connesse. È un esperimento di espansione del contesto; non implementa riepiloghi generativi o un pacchetto GraphRAG esterno.

Graphiti: stato `executed`. Quando eseguito, il runner isolato inserisce manualmente i medesimi claim e usa gli stessi vettori deterministici. Non valuta estrazione, riconciliazione delle identità o invalidazione delle contraddizioni durante l'ingestione.

Riproduzione dalla radice del repository:

```bash
uv run python scripts/evaluate_retrieval.py
# Graphiti rimane in un ambiente temporaneo separato dall'app:
uv venv --python 3.12 /tmp/raven-graphiti-eval
uv pip install --python /tmp/raven-graphiti-eval/bin/python 'graphiti-core[kuzu]==0.30.1' 'httpx==0.28.1'
PYTHONPATH=src /tmp/raven-graphiti-eval/bin/python -m raven.evaluation.graphiti_runner --fixture fixtures/evaluation/rx41-retrieval.json --top-k 6 --output /tmp/raven-graphiti-benchmark.json
# Per includere un risultato Graphiti realmente eseguito:
uv run python scripts/evaluate_retrieval.py --graphiti-result /tmp/raven-graphiti-benchmark.json
```

I risultati puntuali, le omissioni, le fonti restituite e le durate sono nel JSON accanto a questo rapporto. La fixture contiene i gold espliciti per negazioni, date, importi e valuta, omonimie, eliminazione e isolamento del caso.
Graphiti 0.30.1 usa qui il backend Kuzu 0.11.3 per un esperimento temporaneo. Kuzu è deprecato: questa scelta non è una proposta per la produzione. Il confronto delle opzioni e le fonti ufficiali sono nel documento [Graphiti e recupero del grafo](graph-retrieval-options.md).

Limiti: dataset piccolo e costruito per regressioni; nessuna validazione su indagini reali, nessuna misura di qualità semantica degli embedding e nessuna previsione dei tempi di produzione. L'assenza di errori in questi controlli non prova l'accuratezza investigativa generale.
