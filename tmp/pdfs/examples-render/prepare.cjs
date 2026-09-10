const fs=require('fs'), base='/Users/administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/';
const {marked}=require(base+'marked'), sharp=require(base+'sharp');
const dir='tmp/pdfs/examples-render/';
const wrap=s=>s.replace(/<br\s*\/?\s*>/g,'\n').split('\n').flatMap(line=>{let out=[],cur='';for(const w of line.split(/\s+/)){if((cur+' '+w).length>37&&cur){out.push(cur);cur=w}else cur+=(cur?' ':'')+w;}out.push(cur);return out;}).join('\n');
(async()=>{const viz=await(await import(base+'@viz-js/viz/dist/viz.js')).instance();
const tokens=marked.lexer(fs.readFileSync('docs/graph-analysis-methods.md','utf8'));let n=0;
for(const t of tokens){if(t.type!=='code'||t.lang!=='mermaid')continue;n++;
const nodes=new Map(),edges=[],direction=/flowchart\s+(LR|TD|TB)/.exec(t.text)?.[1]||'TD';
const expr=/([\w]+)(?:\[(?:"([^"]*)"|([^\]]*))\]|\{(?:"([^"]*)"|([^}]*))\})?/g;
for(let line of t.text.split('\n')){line=line.trim();if(!line||/^(flowchart|graph|%%|style|classDef|class |subgraph|end\b)/.test(line))continue;
const parts=line.split(/\s*(-->|-.->|==>)\s*/);
function node(part){const label=/^\|([^|]+)\|\s*/.exec(part);if(label)part=part.slice(label[0].length);const m=[...part.matchAll(expr)][0];if(!m)throw Error('Unparsed '+line);const txt=m[2]??m[3]??m[4]??m[5];if(txt!==undefined)nodes.set(m[1],{label:wrap(txt),shape:m[4]!==undefined||m[5]!==undefined?'diamond':'box'});else if(!nodes.has(m[1]))nodes.set(m[1],{label:m[1],shape:'box'});return{id:m[1],label:label?.[1]||''};}
let prev=node(parts[0]);for(let k=2;k<parts.length;k+=2){const next=node(parts[k]);edges.push([prev.id,next.id,next.label]);prev=next;}}
const q=JSON.stringify;const dot=`digraph G {graph [rankdir=${direction==='LR'?'LR':'TB'},bgcolor="white",pad="0.2",nodesep="0.25",ranksep="0.32"];node [fontname="Arial",fontsize=13,style="rounded,filled",fillcolor="#edf3f8",color="#879aad",margin="0.12,0.10"];edge [fontname="Arial",fontsize=11,color="#54758e"];`+[...nodes].map(([id,v])=>`${id} [label=${q(v.label)},shape=${v.shape}];`).join('\n')+edges.map(([a,b,l])=>`${a}->${b} [label=${q(l)}];`).join('\n')+'}';
const svg=viz.renderString(dot,{format:'svg'});await sharp(Buffer.from(svg),{density:170}).png().toFile(dir+`figure-${n}.png`);t.figure=dir+`figure-${n}.png`;}
fs.writeFileSync(dir+'tokens.json',JSON.stringify(tokens));console.log(`Prepared ${tokens.length} blocks and ${n} diagrams`);})();
