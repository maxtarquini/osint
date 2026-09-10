from pathlib import Path
import re,json
root=Path('tmp/pdfs/examples-render');p=Path('docs/graph-analysis-methods.md');s=p.read_text()
patches=json.loads((root/'insertions-metodi.json').read_text())+json.loads((root/'insertions-pipeline.json').read_text())
heads=list(re.finditer(r'^(#{1,6}) (.+)$',s,re.M));edits=[];seen=set()
for patch in patches:
 target=patch['heading'];hits=[i for i,m in enumerate(heads) if m[2]==target]
 if len(hits)!=1:raise ValueError(f'Heading not unique: {target}')
 if target in seen:raise ValueError(f'Duplicate patch: {target}')
 seen.add(target);i=hits[0];level=len(heads[i][1]);end=next((m.start() for m in heads[i+1:] if len(m[1])<=level),len(s))
 fragment=patch['markdown'].strip()
 if re.search(r'^#{1,6} ',fragment,re.M):raise ValueError('New heading unexpected '+target)
 edits.append((end,fragment))
(root/'before-integration.md').write_text(s)
grouped={}
for end,fragment in edits:grouped.setdefault(end,[]).append(fragment)
for end,fragments in sorted(grouped.items(),reverse=True):s=s[:end].rstrip()+'\n\n'+'\n\n'.join(fragments)+'\n\n'+s[end:]
p.write_text(s)
print('Integrated',len(edits),'example blocks at section boundaries')
