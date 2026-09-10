from pathlib import Path
import re,json
from pypdf import PdfReader
from PIL import Image,ImageDraw
root=Path('tmp/pdfs/examples-render');s=Path('docs/graph-analysis-methods.md').read_text()
heads={re.sub(r'[^\w\-]','',h.replace('`','').lower().replace(' ','-')) for h in re.findall(r'^#{1,6} (.+)$',s,re.M)}
errors=[];links=re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',s)
for link in links:
 if link.startswith('#') and link[1:] not in heads:errors.append('Unknown heading '+link)
 elif not link.startswith('#') and not re.match(r'[a-z]+://',link) and not (Path('docs')/link.split('#')[0]).exists():errors.append('Missing file '+link)
r=PdfReader('output/pdf/graph-analysis-methods.pdf')
for i,p in enumerate(r.pages,1):
 t=p.extract_text()
 if len(t.strip())<90:errors.append(f'Almost empty page {i}')
 if '\ufffd' in t or '\u25a0' in t:errors.append(f'Replacement glyph page {i}')
imgs=sorted(root.glob('page-*.png'))
for start in range(0,len(imgs),6):
 sheet=Image.new('RGB',(1440,1450),'#dce2e8');d=ImageDraw.Draw(sheet)
 for j,path in enumerate(imgs[start:start+6]):
  im=Image.open(path).convert('RGB');im.thumbnail((466,690));x=(j%3)*480+(480-im.width)//2;y=(j//3)*725+25;sheet.paste(im,(x,y));d.text(((j%3)*480+12,(j//3)*725+6),path.stem,fill='black')
 sheet.save(root/f'contact-{start//6+1}.png')
print(json.dumps({'pages':len(r.pages),'words':len(s.split()),'links':len(links),'errors':errors},ensure_ascii=False))
if errors:raise SystemExit(1)
