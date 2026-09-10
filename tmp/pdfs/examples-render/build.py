import json,re,html
from pathlib import Path
from reportlab import rl_config
rl_config.useA85=0
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,KeepTogether
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
D=Path('tmp/pdfs/examples-render')
FONT='/System/Library/Fonts/Supplemental/'
for name,file in [('Arial','Arial.ttf'),('Arial-Bold','Arial Bold.ttf'),('Arial-Italic','Arial Italic.ttf'),('Arial-BoldItalic','Arial Bold Italic.ttf'),('Mono','Andale Mono.ttf')]:pdfmetrics.registerFont(TTFont(name,FONT+file))
pdfmetrics.registerFontFamily('Arial',normal='Arial',bold='Arial-Bold',italic='Arial-Italic',boldItalic='Arial-BoldItalic')
S=getSampleStyleSheet()
for name in S.byName:S[name].fontName='Arial'
S.add(ParagraphStyle(name='Body',fontName='Arial',fontSize=10.2,leading=14.8,spaceAfter=7,allowWidows=0,allowOrphans=0,textColor=colors.HexColor('#243749')))
S.add(ParagraphStyle(name='Cell',parent=S['Body'],fontSize=8.2,leading=11,spaceAfter=1,splitLongWords=True))
S.add(ParagraphStyle(name='Quote',parent=S['Body'],fontSize=9.5,leading=13.7,leftIndent=12,rightIndent=10,borderPadding=9,borderColor=colors.HexColor('#bed0de'),borderWidth=.6,backColor=colors.HexColor('#f1f5f8'),spaceBefore=6,spaceAfter=10))
S.add(ParagraphStyle(name='CodeWrap',parent=S['Body'],fontName='Mono',fontSize=8.2,leading=11.5,backColor=colors.HexColor('#f1f5f8'),borderPadding=8))
for name,size,lead in [('Title',25,30),('Heading1',18,23),('Heading2',14,18),('Heading3',11.6,15)]:
 S[name].keepWithNext=True;S[name].fontName='Arial-Bold';S[name].fontSize=size;S[name].leading=lead;S[name].textColor=colors.HexColor('#123e5a');S[name].spaceBefore=15;S[name].spaceAfter=9
W=481;anchors=set()
def slug(s):return re.sub(r'[^\w\-]','',s.replace('`','').lower().replace(' ','-'))
def inline(tokens):
 out=''
 for t in tokens:
  ty=t['type'];text=t.get('text','')
  if ty=='text':out+=inline(t['tokens']) if t.get('tokens') else html.escape(text)
  elif ty=='escape':out+=html.escape(text)
  elif ty=='strong':out+='<b>'+inline(t['tokens'])+'</b>'
  elif ty=='em':out+='<i>'+inline(t['tokens'])+'</i>'
  elif ty=='codespan':out+='<font name="Mono" size="8.2">'+html.escape(text)+'</font>'
  elif ty=='link':
   href=t['href'];content=inline(t['tokens'])
   if href.startswith(('#','http://','https://')):out+='<link href="'+html.escape(href,quote=True)+'" color="#1b607f">'+content+'</link>'
   else:out+=content
  elif ty=='br':out+='<br/>'
  elif ty=='html':out+=html.escape(t.get('raw',''))
  else:out+=html.escape(text)
 return out.replace('\n',' ')
def para(t,style='Body'):
 text=inline(t.get('tokens',[])) or html.escape(t.get('text',''))
 if style=='Cell':text=text.replace('size="8.2"','size="7.4"')
 return Paragraph(text,S[style])
def build(tokens):
 result=[]
 for t in tokens:
  ty=t['type']
  if ty=='space':continue
  if ty=='heading':
   anchor=slug(t['text']);prefix=''
   if anchor not in anchors:prefix='<a name="'+anchor+'"/>';anchors.add(anchor)
   result.append(Paragraph(prefix+inline(t['tokens']),S['Title' if t['depth']==1 else 'Heading'+str(min(t['depth']-1,3))]))
  elif ty in ('paragraph','text'):result.append(para(t))
  elif ty=='blockquote':
   pieces=[]
   for b in t['tokens']:
    if b['type']=='space':continue
    if b.get('tokens'):pieces.append(inline(b['tokens']))
    else:pieces.append(html.escape(b.get('text','')))
   result.append(Paragraph('<br/><br/>'.join(pieces),S['Quote']))
  elif ty=='list':
   for i,item in enumerate(t['items']):
    cells=build(item['tokens']);bullet=f'{i+1}.' if t.get('ordered') else '•'
    result.append(Table([[Paragraph(bullet,S['Body']),cells]],colWidths=[18,W-18],style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)])))
  elif ty=='table':
   rows=[[para(c,'Cell') for c in t['header']]]+[[para(c,'Cell') for c in row] for row in t['rows']]
   count=len(t['header']);widths=[W/count]*count
   if count==2:widths=[W*.31,W*.69]
   elif count==3:widths=[W*.27,W*.365,W*.365]
   elif count==4:widths=[W*.29,W*.23,W*.25,W*.23]
   tab=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
   tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce8f0')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f6f8fa')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#a2b7c7'))]))
   result.extend([tab,Spacer(1,10)])
  elif ty=='code':
   if t.get('figure'):
    w,h=ImageReader(t['figure']).getSize();factor=min(W/w,580/h);result.extend([Image(t['figure'],w*factor,h*factor),Spacer(1,8)])
   else:
    code=t['text']
    if t.get('lang')=='json':code=json.dumps(json.loads(code),ensure_ascii=False,indent=2)
    result.append(Paragraph(html.escape(code).replace(' ','&#160;').replace('\n','<br/>'),S['CodeWrap']))
  elif ty=='hr':result.append(Spacer(1,12))
  else:raise ValueError('Unhandled '+ty)
 grouped=[];i=0
 while i<len(result):
  item=result[i]
  if isinstance(item,Paragraph) and item.style.name=='Quote':
   group=[item];i+=1
   if i<len(result) and isinstance(result[i],Paragraph) and result[i].style.name=='CodeWrap':
    group.append(result[i]);i+=1
    if i<len(result) and isinstance(result[i],Paragraph) and result[i].style.name=='Quote':group.append(result[i]);i+=1
   if i<len(result) and isinstance(result[i],Table):group.append(result[i]);i+=1
   grouped.append(KeepTogether(group))
  elif isinstance(item,Table):grouped.append(KeepTogether([item]));i+=1
  elif isinstance(item,Image) and i+2<len(result) and isinstance(result[i+1],Spacer) and isinstance(result[i+2],Paragraph) and result[i+2].getPlainText().startswith('Figura '):grouped.append(KeepTogether(result[i:i+3]));i+=3
  else:grouped.append(item);i+=1
 return grouped
story=build(json.loads((D/'tokens.json').read_text()))
def page(c,doc):
 c.saveState();c.setStrokeColor(colors.HexColor('#cad6de'));c.setLineWidth(.5);c.line(57,802,538,802);c.setFont('Arial',8);c.setFillColor(colors.HexColor('#647b8b'));c.drawString(57,811,'RAVEN  /  ESTRAZIONE DEL GRAFO');c.drawRightString(538,811,'Manuale tecnico · 10 settembre 2026');c.drawString(57,31,'Algoritmi, agenti, prompt e workflow');c.drawRightString(538,31,str(doc.page));c.restoreState()
class ManualDoc(SimpleDocTemplate):
 def afterFlowable(self,f):
  if isinstance(f,Paragraph) and f.style.name in ('Heading1','Heading2'):
   key='outline-'+str(self.seq.nextf('outline'));self.canv.bookmarkPage(key);self.canv.addOutlineEntry(f.getPlainText(),key,level=0 if f.style.name=='Heading1' else 1,closed=False)
doc=ManualDoc('output/pdf/graph-analysis-methods.pdf',pagesize=(595,842),rightMargin=57,leftMargin=57,topMargin=57,bottomMargin=53,title='Raven - Metodi di analisi e generazione dei grafi',author='Raven',pageCompression=1)
doc.build(story,onFirstPage=page,onLaterPages=page)
print('PDF written')
