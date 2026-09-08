from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Frame, Table, TableStyle, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader

ROOT=Path('/Users/administrator/WORK/Progetti/OSINT/osint')
OUT=ROOT/'test-case/geopolica/supporto/00_guida_importazione_e_verifica.pdf'
for name,file in [('Body','Arial.ttf'),('Bold','Arial Bold.ttf')]:
 pdfmetrics.registerFont(TTFont(name,'/System/Library/Fonts/Supplemental/'+file))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')
navy=colors.HexColor('#193449');teal=colors.HexColor('#18786E');gray=colors.HexColor('#52626C')
styles={
 'title':ParagraphStyle('title',fontName='Bold',fontSize=24,leading=28,textColor=navy,spaceAfter=15),
 'head':ParagraphStyle('head',fontName='Bold',fontSize=13,leading=17,textColor=teal,spaceBefore=8,spaceAfter=7),
 'body':ParagraphStyle('body',fontName='Body',fontSize=11,leading=16,textColor=navy,spaceAfter=10),
 'meta':ParagraphStyle('meta',fontName='Body',fontSize=9,leading=13,textColor=gray,spaceAfter=10),
 'small':ParagraphStyle('small',fontName='Body',fontSize=9,leading=13,textColor=navy),
 'box':ParagraphStyle('box',fontName='Body',fontSize=10,leading=15,textColor=navy,backColor=colors.HexColor('#EDF5F3'),borderPadding=10,spaceBefore=8,spaceAfter=18),
}
def P(text,style='body'):return Paragraph(text,styles[style])
def table(rows,widths):
 t=Table([[P(x,'small') for x in row] for row in rows],colWidths=widths,hAlign='LEFT')
 t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E2EEEB')),('LINEBELOW',(0,0),(-1,-1),0.4,colors.HexColor('#CCDAD7')),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
 return t
pages=[
 [P('RX41 | Guida di supporto','title'),
  P('Cartella geopolica - scenario interamente fittizio - 8 settembre 2026','meta'),
  P('Il test riguarda terrorismo ed estremismo, con particolare attenzione a identità, provenienza delle affermazioni e loro evoluzione nel tempo. Tutti i soggetti, gli eventi e gli atti RX41 sono inventati. Questa guida valuta la coerenza delle risposte con il corpus; non certifica fatti del mondo reale.'),
  P('Preparazione dell’indagine','head'),
  P('Usa il file briefing_investigazione.md per copiare nome, contesto e domande in Raven. Seleziona italiano e il dominio Terrorism and extremism (TERRORISM_EXTREMISM). Importa dalla cartella geopolica i tre PDF elencati qui sotto, mantenendo le sigle D1, D2 e D3 per orientarti nei risultati.'),
  table([['Sigla','File originale nella cartella','Pagine'],['D1','46fce612-cb70-431c-b859-ef819743186d.pdf<br/>Fascicolo sintetico iniziale','8'],['D2','2dde1f01-0f16-4b16-a722-3c622a3c6d42.pdf<br/>Connessioni e nuove fonti - 1 marzo 2026','5'],['D3','b6e69ce5-ed81-4262-abd0-9dd2d3b74271.pdf<br/>Smentite, rettifiche e limiti - 5 marzo 2026','5']],[40,405,54]),
  Spacer(1,10),
  P('<b>Materiale di controllo.</b> Importa soltanto D1, D2 e D3 come evidenze. La guida contiene le risposte attese e deve restare fuori dal corpus. I numeri di pagina successivi indicano le pagine fisiche di questi PDF.','box'),
  P('Due tempi da conservare','head'),
  table([['Tempo del fatto','Tempo della registrazione o rettifica'],['10 febbraio: data riferita dell’attacco','12 febbraio: compilazione di C-03; 5 marzo: correzione di RT-04'],['21 febbraio - 2 marzo: supporto grafico attivo','1 marzo: rapporto ancora attivo; 5 marzo: cessazione riferita con effetto dal 3 marzo']],[220,279]),
  Spacer(1,10),
  P('Schema di lettura: affermazione iniziale → nuova fonte → eventuale rettifica → stato riferito alla data richiesta. Un aggiornamento può correggere un errore oppure descrivere un cambiamento reale nello scenario.','meta')],
 [P('Verifiche | Identità ed eventi','title'),
  P('Risultati attesi costruiti editorialmente sui tre documenti; non costituiscono una valutazione indipendente del modello. Ogni risposta dovrebbe riportare citazioni puntuali e attribuzioni.','meta'),
  P('1. Rapporti organizzativi e fonti','head'),
  P('D1 p. 1 descrive Ramo Est come affiliata del Fronte e Cerchio Grigio come autonomo. D2 p. 1 aggiunge l’affiliazione di Unione Levante e l’accusa anonima SA-02 su Cerchio Grigio. D3 p. 1 registra la smentita interessata CG-01: non è il ritiro di SA-02 né una verifica indipendente. La trascrizione NI-01 non raddoppia le conferme della Scheda Registro Levante. L’assenza di nuove fonti non smentisce Unione Levante.'),
  P('2. Correzione della data dell’attacco','head'),
  P('Confrontare D1 p. 3, D2 p. 4 e D3 p. 4. La data dell’Attacco di Piazza Lume è rettificata al 10 febbraio 2026; l’11 febbraio in RT-04 viene riconosciuto come errore di trascrizione. L’11 febbraio resta la data della distinta Crisi degli ostaggi di Sala Niva. Operazione Vetro è l’operazione collegata ai due eventi e non va fusa con essi. L’ora di conclusione della crisi resta sconosciuta.'),
  P('3. Responsabilità e posizione geografica','head'),
  P('D2 p. 4 presenta come accertata la responsabilità di Nucleo Bruma. D3 p. 4 ritira questa certezza: la responsabilità resta ipotizzata, non confermata e non esclusa. La stessa pagina ritira Valle Torva quale localizzazione di Casa Nebbia, senza indicare un’alternativa. D1 p. 4 ne descrive l’uso ma non la posizione: non ricavare coordinate o collocazioni dalla vicinanza dei nomi nel testo.'),
  P('4. Nomi simili e rettifiche circoscritte','head'),
  P('D1 p. 7 distingue Ramo Est da Lista Civica Ramo Est. D2 p. 2 ipotizza una fusione fra Canale Prisma e Laboratorio Prisma; D3 p. 2 ritira l’ipotesi. Conservare due identità distinte. La rettifica non dimostra l’assenza universale di rapporti tra esse e non ritira le attribuzioni editoriali di CE-03.'),
  P('<b>Controllo trasversale.</b> Una rettifica va applicata alla specifica affermazione che corregge. Non rende falso l’intero documento precedente e non cancella la sua utilità per ricostruire la storia dell’informazione.','box')],
 [P('Verifiche | Importi e rapporti civili','title'),
  P('5. Un versamento, più resoconti','head'),
  P('D1 p. 6, D2 p. 3 e D3 p. 3 descrivono lo stesso versamento di 240 euro del 16 febbraio 2026, dall’Associazione Sportiva Ponte al Centro Civico Aurora, con causale educativa. Le ripetizioni non generano altri pagamenti né un totale di 720 euro. ST-05 accusa il Centro di un successivo trasferimento a Rete Passaggio, senza data o riscontri allegati.'),
  P('EC-03, in D3 p. 3, è emesso dal beneficiario e smentisce il trasferimento di quel contributo per l’intervallo 16 febbraio-4 marzo 2026. Accusa e smentita restano attribuite. La destinazione a Programma Ritorno non è determinata: l’assenza del nome sulla ricevuta non dimostra né esclude l’uso dei materiali nel programma.'),
  P('6. Cessazione del supporto grafico','head'),
  P('D2 p. 5 e D3 p. 5 descrivono una sequenza coerente: supporto del Laboratorio al Centro attivo dal 21 febbraio al 2 marzo inclusi, cessato dal 3 marzo. Era quindi attivo al 1 marzo. La cessazione comunicata il 5 marzo non significa che la collaborazione non sia mai esistita.'),
  P('7. Collaborazione educativa e ruoli civili','head'),
  P('D2 p. 5 e D3 p. 5 riferiscono che Biblioteca Quercia collabora con il Centro per Programma Ritorno dal 20 febbraio e che il rapporto prosegue al 5 marzo. Non dedurre una durata illimitata. La cessazione del supporto grafico non riguarda questa relazione. D1 pp. 5, 7-8 e D3 p. 5 mantengono distinti prevenzione, attività culturali e appartenenza estremista: Cellula Verde è un circolo di lettura.'),
  P('<b>Negazione con un ambito preciso.</b> “Non ha trasferito questo contributo in questo periodo” non equivale a “non ha mai trasferito nulla”. Analogamente, “non è una cellula terroristica” non nega l’esistenza di un circolo culturale.','box'),
  P('Valutazione pratica della risposta','head'),
  P('Per ogni domanda, controlla se la citazione raggiunge il passaggio corretto, se la fonte è identificata e se tempo, quantità e negazioni mantengono il loro ambito. Segnala separatamente una risposta incompleta, una citazione sbagliata e una conclusione non sostenuta: sono errori diversi. Le spiegazioni già presenti nei fascicoli facilitano il test; il set non misura prestazioni su fonti nuove prive di annotazioni.'),
  P('Riferimenti: esclusivamente i tre fascicoli locali elencati a pagina 1. Nessuna fonte esterna aggiunta.','meta')]
]
W,H=A4
c=canvas.Canvas(str(OUT),pagesize=A4)
c.setTitle('RX41 - Guida di importazione e verifica')
c.setAuthor('Raven OSINT - materiale di supporto editoriale')
for i,story in enumerate(pages,1):
 c.setFillColor(teal);c.rect(0,H-8,W,8,fill=1,stroke=0)
 c.setFont('Bold',9);c.drawString(48,H-35,'RAVEN  /  RX41  /  SUPPORTO ALLA VERIFICA')
 c.setFillColor(gray);c.setFont('Body',8)
 c.drawString(48,25,'SCENARIO FITTIZIO | Non importare come evidenza')
 c.drawRightString(W-48,25,f'Pagina {i} di {len(pages)}')
 c.setStrokeColor(colors.HexColor('#CCDAD7'));c.line(48,40,W-48,40)
 frame=Frame(48,54,W-96,H-112,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
 frame.addFromList(story,c)
 if story:raise RuntimeError(f'Overflow a pagina {i}: {len(story)} blocchi')
 c.showPage()
c.save()
r=PdfReader(OUT)
assert len(r.pages)==3
for i,p in enumerate(r.pages,1):
 t=p.extract_text();assert f'Pagina {i} di 3' in t and '\ufffd' not in t
 print('Pagina',i,'caratteri',len(t))
print(OUT)
