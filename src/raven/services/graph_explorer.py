"""Self-contained browser explorer used by investigation graph exports."""

# ruff: noqa: E501 -- CSS/JavaScript and standalone HTML stay readable as browser source.

from __future__ import annotations

import html
import json

_STYLE = r"""
:root {
  color-scheme: dark;
  --bg: #06100f;
  --panel: #0d211f;
  --panel-strong: #091817;
  --line: #1f5b50;
  --accent: #42e8bd;
  --ink: #e5f4f0;
  --muted: #8aa6a1;
  --blue: #79b8ff;
  --warning: #f8cc5b;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 14px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow: hidden;
}
button, input, select { font: inherit; }
button, input, select {
  min-height: 38px;
  border: 1px solid #456f68;
  background: #0b1a19;
  color: var(--ink);
  border-radius: 5px;
  padding: 7px 10px;
}
button { cursor: pointer; font-weight: 700; white-space: nowrap; }
button:hover, button:focus-visible, input:focus-visible, select:focus-visible {
  border-color: var(--accent);
  color: var(--accent);
  outline: 2px solid color-mix(in srgb, var(--accent) 35%, transparent);
  outline-offset: 1px;
}
button[aria-pressed="true"], .primary {
  background: #0d594d;
  border-color: var(--accent);
  color: #fff;
}
header {
  min-height: 116px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-strong);
  display: grid;
  gap: 8px;
}
.toolbar { display: flex; gap: 8px; align-items: center; min-width: 0; }
.heading { min-width: 245px; max-width: 360px; }
h1 { margin: 0 0 4px; color: var(--accent); font-size: 17px; }
.meta, .help { color: var(--muted); font-size: 12px; }
.search-group { display: flex; flex: 1; min-width: 260px; }
.search-group input { flex: 1; min-width: 120px; border-radius: 5px 0 0 5px; }
.search-group button, .search-group output { border-radius: 0; border-left: 0; }
.search-group output {
  min-width: 64px;
  display: grid;
  place-items: center;
  border-top: 1px solid #456f68;
  border-bottom: 1px solid #456f68;
  color: var(--muted);
}
.viewport-controls, .filter-controls, .action-controls, .path-controls {
  display: flex;
  gap: 6px;
  align-items: center;
}
.viewport-controls input[type="range"] { width: 125px; min-height: 30px; padding: 0; }
.viewport-controls output { min-width: 48px; color: var(--accent); text-align: center; }
.filter-controls { flex: 1; min-width: 0; }
.filter-controls select { min-width: 125px; max-width: 210px; }
.confidence { display: flex; gap: 7px; align-items: center; color: var(--muted); white-space: nowrap; }
.confidence input { min-height: 30px; width: 120px; padding: 0; }
.scope-status {
  min-height: 28px;
  padding: 5px 14px;
  color: var(--muted);
  background: #071513;
  border-bottom: 1px solid #173d37;
}
.scope-status strong { color: var(--accent); }
.scope-status[data-readable="true"]::after {
  content: " · readable zoom; pan to explore the complete graph";
  color: var(--warning);
}
main {
  height: calc(100vh - 202px);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  min-height: 260px;
}
main.inspector-hidden { grid-template-columns: minmax(0, 1fr); }
main.inspector-hidden aside { display: none; }
.canvas-shell { min-width: 0; position: relative; overflow: hidden; }
#cy {
  width: 100%;
  height: 100%;
  background: radial-gradient(circle at center, #102a27 0, #071311 72%);
}
aside {
  border-left: 1px solid var(--line);
  background: var(--panel);
  padding: 16px;
  overflow: auto;
}
aside h2 { margin: 0 0 12px; color: var(--accent); font-size: 14px; }
.field { padding: 9px 0; border-bottom: 1px solid #173d37; overflow-wrap: anywhere; }
.field b { display: block; color: var(--muted); font-size: 11px; margin-bottom: 4px; }
.selection-list { margin: 8px 0 0; padding-left: 20px; }
footer {
  min-height: 58px;
  padding: 8px 14px;
  border-top: 1px solid var(--line);
  background: var(--panel-strong);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
footer .divider { width: 1px; height: 30px; background: var(--line); }
.path-label { max-width: 160px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.path-label strong { color: var(--blue); }
.context-menu {
  position: absolute;
  z-index: 20;
  display: grid;
  width: 220px;
  padding: 6px;
  border: 1px solid var(--accent);
  border-radius: 7px;
  background: #0b1a19;
  box-shadow: 0 14px 40px #000a;
}
.context-menu[hidden] { display: none; }
.context-menu button { border: 0; text-align: left; background: transparent; }
.context-menu button:hover, .context-menu button:focus-visible { background: #12312d; }
.empty-state {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  pointer-events: none;
}
.empty-state[hidden] { display: none; }
#fallback {
  position: absolute;
  inset: 132px 24px 72px;
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 18px;
  z-index: 30;
}
.error { color: #ff6b70; margin-bottom: 14px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 9px; text-align: left; border-bottom: 1px solid #173d37; }
th { color: var(--accent); position: sticky; top: 0; background: var(--panel); }
dialog {
  width: min(1100px, 92vw);
  max-height: 82vh;
  color: var(--ink);
  background: var(--panel);
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 0;
}
dialog::backdrop { background: #000b; }
.dialog-header { position: sticky; top: 0; display: flex; justify-content: space-between;
  align-items: center; padding: 12px 16px; background: var(--panel-strong); border-bottom: 1px solid var(--line); }
.dialog-header h2 { margin: 0; color: var(--accent); font-size: 15px; }
.dialog-body { max-height: calc(82vh - 64px); overflow: auto; padding: 8px 16px 16px; }
@media (max-width: 1400px) {
  header { min-height: 164px; }
  .toolbar { flex-wrap: wrap; }
  .heading { min-width: 220px; }
  main { height: calc(100vh - 250px); grid-template-columns: minmax(0, 1fr) 300px; }
  footer { overflow-x: auto; }
}
@media (max-width: 820px) {
  body { overflow: auto; }
  header { min-height: 210px; }
  .heading { max-width: none; width: 100%; }
  .search-group { min-width: 100%; }
  .filter-controls { overflow-x: auto; padding-bottom: 4px; }
  main { height: calc(100vh - 296px); grid-template-columns: 1fr; }
  aside { display: none; }
  #toggle-inspector { display: none; }
}
"""


_SCRIPT = r"""
(() => {
  'use strict';
  if (typeof cytoscape === 'undefined') return;

  const elements = __RAVEN_ELEMENTS__;
  const storageKey = __RAVEN_STORAGE_KEY__;
  const byId = (id) => document.getElementById(id);
  const controls = {
    search: byId('search'), searchCount: byId('search-count'), type: byId('type'),
    status: byId('status'), relationship: byId('relationship'), direction: byId('direction'),
    confidence: byId('confidence'), confidenceValue: byId('confidence-value'),
    layout: byId('layout'), zoom: byId('zoom'), zoomValue: byId('zoom-value'),
    scope: byId('scope-status'), inspector: byId('inspector'), main: byId('workspace'),
    empty: byId('empty-state'), context: byId('context-menu'),
    source: byId('path-source'), target: byId('path-target')
  };
  const state = {
    searchMatches: [], searchIndex: -1, focusIds: null, hiddenIds: new Set(),
    pathNodeIds: new Set(), pathEdgeIds: new Set(), sourceId: null, targetId: null,
    contextId: null, history: [], future: [], restoring: false
  };
  const MIN_READABLE_ZOOM = 0.72;
  const colors = {
    PERSON:'#5eead4', ORGANIZATION:'#86efac', LOCATION:'#fde68a', FACILITY:'#f0abfc',
    EVENT:'#fca5a5', DATE:'#c4b5fd', URL:'#7dd3fc', DOMAIN:'#7dd3fc',
    IP_ADDRESS:'#93c5fd', EMAIL_ADDRESS:'#67e8f9', FILE_HASH:'#d8b4fe'
  };
  elements.filter((item) => item.data.kind === 'entity').forEach((item) => {
    item.data.color = colors[item.data.type] || '#d1d5db';
    item.data.display = `${item.data.label}\n◇ ${String(item.data.type).replaceAll('_', ' ')}`;
  });

  const cy = cytoscape({
    container: byId('cy'), elements, minZoom: 0.05, maxZoom: 4,
    selectionType: 'additive', boxSelectionEnabled: true,
    style: [
      { selector:'node', style:{
        'shape':'round-rectangle', 'width':170, 'height':64, 'padding':'6px',
        'background-color':'#0b1a19', 'label':'data(display)', 'color':'data(color)',
        'font-family':'monospace', 'font-size':14, 'font-weight':600, 'line-height':1.4,
        'text-wrap':'wrap', 'text-max-width':190, 'text-valign':'center', 'text-halign':'center',
        'border-width':2, 'border-color':'data(color)', 'overlay-opacity':0
      }},
      { selector:'edge', style:{
        'width':2, 'line-color':'#638b84', 'target-arrow-color':'#638b84',
        'target-arrow-shape':'triangle', 'curve-style':'bezier', 'label':'data(label)',
        'color':'#a9c4bf', 'font-family':'monospace', 'font-size':9,
        'text-background-color':'#071311', 'text-background-opacity':0.92,
        'text-background-padding':3, 'text-rotation':'autorotate'
      }},
      { selector:'[status = "verified"]', style:{
        'border-width':4, 'line-color':'#42e8bd', 'target-arrow-color':'#42e8bd'
      }},
      { selector:'[status = "rejected"]', style:{'opacity':0.3, 'line-style':'dashed'} },
      { selector:':selected', style:{
        'background-color':'#173d37', 'border-color':'#fff', 'border-width':5,
        'line-color':'#fff', 'target-arrow-color':'#fff', 'z-index':999
      }},
      { selector:'.search-match', style:{
        'border-color':'#f8cc5b', 'border-width':5, 'line-color':'#f8cc5b',
        'target-arrow-color':'#f8cc5b', 'z-index':900
      }},
      { selector:'.path', style:{
        'border-color':'#ff9f43', 'border-width':5, 'line-color':'#ff9f43',
        'target-arrow-color':'#ff9f43', 'z-index':950
      }},
      { selector:'edge.path', style:{'width':5} },
      { selector:'.dimmed', style:{'opacity':0.1, 'text-opacity':0.08} },
      { selector:'.concealed', style:{'display':'none'} }
    ]
  });
  byId('fallback').style.display = 'none';

  const layoutOptions = (name) => ({
    name, fit:true, padding:70, animate:cy.elements().length < 300,
    animationDuration:260, nodeDimensionsIncludeLabels:true, avoidOverlap:true,
    spacingFactor:1.45, componentSpacing:170, idealEdgeLength:180, nodeRepulsion:12000,
    directed:name === 'breadthfirst'
  });
  const edgeEndpoints = (edge) => [edge.source().id(), edge.target().id()];
  const visibleElements = () => cy.elements().not('.concealed');
  const fitReadable = () => {
    const visible = visibleElements();
    if (!visible.length) return;
    cy.fit(visible, 70);
    if (cy.zoom() < MIN_READABLE_ZOOM) {
      cy.zoom(MIN_READABLE_ZOOM);
      cy.center(visible);
      controls.scope.dataset.readable = 'true';
    } else {
      delete controls.scope.dataset.readable;
    }
  };
  const selectedNodes = () => cy.nodes(':selected').toArray();
  const selectedNodeIds = () => selectedNodes().map((node) => node.id());
  const statusText = (message) => { controls.scope.textContent = message; };
  const nameFor = (id) => id ? (cy.getElementById(id).data('label') || id) : '—';
  const isTyping = (target) => ['INPUT', 'SELECT', 'TEXTAREA'].includes(target?.tagName);

  const field = (label, value) => {
    const row = document.createElement('div'); row.className = 'field';
    const key = document.createElement('b'); key.textContent = label;
    const text = document.createElement('span'); text.textContent = String(value ?? '—');
    row.append(key, text); return row;
  };
  const renderInspector = (item = null) => {
    const selected = selectedNodes();
    if (!item && selected.length === 1) item = selected[0];
    if (!item && selected.length > 1) {
      const list = document.createElement('ul'); list.className = 'selection-list';
      selected.slice(0, 20).forEach((node) => {
        const entry = document.createElement('li'); entry.textContent = node.data('label'); list.append(entry);
      });
      controls.inspector.replaceChildren(
        field('SELECTION', `${selected.length} entities`),
        field('HELP', 'Use Focus, Hide, Source or Target on the selected entities.'), list
      );
      return;
    }
    if (!item) {
      controls.inspector.textContent = 'Select one node or relationship. Ctrl/Cmd or Shift-click selects multiple nodes.';
      return;
    }
    const data = item.data();
    controls.inspector.replaceChildren(
      field(data.kind === 'entity' ? 'ENTITY' : 'RELATIONSHIP', data.label),
      field('TYPE', data.type), field('STATUS', data.status),
      field('CONFIDENCE', `${Math.round(Number(data.confidence || 0) * 100)}%`),
      field('ALIASES', data.aliases), field('IDENTIFIERS', data.identifiers),
      field('EVIDENCE', data.evidence), field('RATIONALE', data.rationale)
    );
  };

  const relationshipMatches = (edge, {forTraversal = false} = {}) => {
    const data = edge.data();
    const relationship = controls.relationship.value;
    const status = controls.status.value;
    const confidence = Number(controls.confidence.value) / 100;
    if (relationship && data.type !== relationship) return false;
    if (status && data.status !== status) return false;
    if (Number(data.confidence || 0) < confidence) return false;
    if (forTraversal && ['rejected', 'archived'].includes(data.status)) return false;
    return true;
  };
  const neighborhood = (roots, depth) => {
    const visited = new Set(roots); let frontier = new Set(roots);
    for (let level = 0; level < depth && frontier.size; level += 1) {
      const next = new Set();
      cy.edges().forEach((edge) => {
        if (!relationshipMatches(edge, {forTraversal:true})) return;
        const [source, target] = edgeEndpoints(edge);
        if (frontier.has(source) && !visited.has(target)) next.add(target);
        if (frontier.has(target) && !visited.has(source)) next.add(source);
      });
      next.forEach((id) => visited.add(id)); frontier = next;
    }
    return visited;
  };
  const reciprocal = (edge) => {
    const [source, target] = edgeEndpoints(edge);
    return cy.edges().some((candidate) => {
      const endpoints = edgeEndpoints(candidate);
      return endpoints[0] === target && endpoints[1] === source;
    });
  };

  const snapshot = () => ({
    type:controls.type.value, status:controls.status.value,
    relationship:controls.relationship.value, direction:controls.direction.value,
    confidence:controls.confidence.value, layout:controls.layout.value,
    focusIds:state.focusIds ? [...state.focusIds] : null, hiddenIds:[...state.hiddenIds],
    pathNodeIds:[...state.pathNodeIds], pathEdgeIds:[...state.pathEdgeIds],
    sourceId:state.sourceId, targetId:state.targetId, selectedIds:selectedNodeIds(),
    zoom:cy.zoom(), pan:cy.pan(), inspectorHidden:controls.main.classList.contains('inspector-hidden'),
    positions:Object.fromEntries(cy.nodes().map((node) => [node.id(), node.position()]))
  });
  const persist = () => {
    try { localStorage.setItem(storageKey, JSON.stringify(snapshot())); } catch (_error) { /* optional */ }
  };
  const remember = () => {
    if (state.restoring) return;
    state.history.push(snapshot());
    if (state.history.length > 30) state.history.shift();
    state.future.length = 0;
    byId('back').disabled = state.history.length === 0;
    byId('forward').disabled = true;
  };

  const updatePathLabels = () => {
    controls.source.innerHTML = `<strong>A</strong> ${escapeHtml(nameFor(state.sourceId))}`;
    controls.target.innerHTML = `<strong>B</strong> ${escapeHtml(nameFor(state.targetId))}`;
  };
  const updateAccessibleTable = () => {
    const body = byId('graph-table-body'); body.replaceChildren();
    cy.nodes().not('.concealed').forEach((node) => {
      const row = body.insertRow();
      ['Entity', node.data('label'), node.data('type'), '—', node.data('confidence'), node.data('status')]
        .forEach((value) => { const cell = row.insertCell(); cell.textContent = String(value); });
    });
    cy.edges().not('.concealed').forEach((edge) => {
      const row = body.insertRow();
      ['Relationship', edge.source().data('label'), edge.data('type'), edge.target().data('label'), edge.data('confidence'), edge.data('status')]
        .forEach((value) => { const cell = row.insertCell(); cell.textContent = String(value); });
    });
  };
  const applyPresentation = ({fit = false, message = ''} = {}) => {
    cy.elements().removeClass('concealed dimmed path');
    const type = controls.type.value; const status = controls.status.value;
    const selectedId = selectedNodeIds().at(-1) || null; const direction = controls.direction.value;
    cy.nodes().forEach((node) => {
      if ((type && node.data('type') !== type) || (status && node.data('status') !== status)
          || state.hiddenIds.has(node.id()) || (state.focusIds && !state.focusIds.has(node.id()))) {
        node.addClass('concealed');
      }
    });
    cy.edges().forEach((edge) => {
      const [source, target] = edgeEndpoints(edge);
      let directional = true;
      if (direction && selectedId) {
        directional = direction === 'outgoing' ? source === selectedId
          : direction === 'incoming' ? target === selectedId
          : (source === selectedId || target === selectedId) && reciprocal(edge);
      }
      if (!relationshipMatches(edge) || !directional || edge.connectedNodes().some((node) => node.hasClass('concealed'))) {
        edge.addClass('concealed');
      }
    });
    if (direction && selectedId) {
      const connected = new Set([selectedId]);
      cy.edges().not('.concealed').forEach((edge) => edgeEndpoints(edge).forEach((id) => connected.add(id)));
      cy.nodes().not('.concealed').forEach((node) => { if (!connected.has(node.id())) node.addClass('concealed'); });
    }
    if (state.pathNodeIds.size) {
      cy.elements().not('.concealed').addClass('dimmed');
      state.pathNodeIds.forEach((id) => cy.getElementById(id).removeClass('dimmed').addClass('path'));
      state.pathEdgeIds.forEach((id) => cy.getElementById(id).removeClass('dimmed').addClass('path'));
    }
    const nodeCount = cy.nodes().not('.concealed').length;
    const edgeCount = cy.edges().not('.concealed').length;
    controls.empty.hidden = nodeCount > 0;
    controls.confidenceValue.textContent = `${controls.confidence.value}%`;
    const scopeMessage = state.pathEdgeIds.size
      ? `Highlighted path · ${state.pathEdgeIds.size} relationships`
      : `${nodeCount} visible entities · ${edgeCount} visible relationships`;
    statusText(message || scopeMessage);
    updateAccessibleTable(); updatePathLabels(); persist();
    if (fit && nodeCount) fitReadable();
  };

  const restore = (saved) => {
    if (!saved) return;
    state.restoring = true;
    controls.type.value = saved.type || ''; controls.status.value = saved.status || '';
    controls.relationship.value = saved.relationship || ''; controls.direction.value = saved.direction || '';
    controls.confidence.value = saved.confidence ?? 0; controls.layout.value = saved.layout || 'cose';
    state.focusIds = saved.focusIds ? new Set(saved.focusIds) : null;
    state.hiddenIds = new Set(saved.hiddenIds || []); state.pathNodeIds = new Set(saved.pathNodeIds || []);
    state.pathEdgeIds = new Set(saved.pathEdgeIds || []); state.sourceId = saved.sourceId || null;
    state.targetId = saved.targetId || null; cy.elements().unselect();
    (saved.selectedIds || []).forEach((id) => cy.getElementById(id).select());
    if (saved.positions) cy.nodes().positions((node) => saved.positions[node.id()] || node.position());
    controls.main.classList.toggle('inspector-hidden', Boolean(saved.inspectorHidden));
    byId('toggle-inspector').setAttribute('aria-expanded', String(!saved.inspectorHidden));
    applyPresentation(); renderInspector();
    if (Number.isFinite(saved.zoom) && saved.pan) { cy.zoom(saved.zoom); cy.pan(saved.pan); }
    state.restoring = false;
  };
  const loadSaved = () => {
    try { return JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch (_error) { return null; }
  };

  const refreshSearch = (step = 0) => {
    const query = controls.search.value.trim().toLocaleLowerCase();
    cy.elements().removeClass('search-match');
    state.searchMatches = query ? cy.elements().filter((item) => {
      const data = item.data();
      return [data.label, data.type, data.aliases, data.identifiers]
        .join(' ').toLocaleLowerCase().includes(query) && !item.hasClass('concealed');
    }).toArray() : [];
    if (!state.searchMatches.length) {
      state.searchIndex = -1; controls.searchCount.textContent = query ? '0/0' : '—'; return;
    }
    state.searchIndex = step === 0 ? 0
      : (state.searchIndex + step + state.searchMatches.length) % state.searchMatches.length;
    const match = state.searchMatches[state.searchIndex]; match.addClass('search-match');
    controls.searchCount.textContent = `${state.searchIndex + 1}/${state.searchMatches.length}`;
    cy.animate({center:{eles:match}, zoom:Math.max(cy.zoom(), 0.75), duration:220});
    if (match.isNode()) { cy.elements().unselect(); match.select(); }
    renderInspector(match);
  };
  const focusSelection = (depth) => {
    const roots = selectedNodeIds();
    if (!roots.length) { statusText('Select at least one entity before focusing.'); return; }
    remember(); state.focusIds = neighborhood(roots, depth); state.pathNodeIds.clear(); state.pathEdgeIds.clear();
    applyPresentation({fit:true, message:`Focused on ${depth}-hop neighborhood · ${state.focusIds.size} entities`});
  };
  const hideSelection = () => {
    const ids = selectedNodeIds(); if (!ids.length) { statusText('Select at least one entity to hide.'); return; }
    remember(); ids.forEach((id) => state.hiddenIds.add(id)); cy.elements().unselect();
    applyPresentation({fit:true, message:`Hidden ${ids.length} selected entities`}); renderInspector();
  };
  const resetView = () => {
    remember(); state.focusIds = null; state.hiddenIds.clear(); state.pathNodeIds.clear(); state.pathEdgeIds.clear();
    state.sourceId = null; state.targetId = null; controls.type.value = ''; controls.status.value = '';
    controls.relationship.value = ''; controls.direction.value = ''; controls.confidence.value = 0;
    cy.elements().unselect(); applyPresentation({fit:true, message:'Graph view reset'}); renderInspector();
  };
  const markEndpoint = (key) => {
    const ids = selectedNodeIds();
    if (ids.length !== 1) { statusText('Select exactly one entity for a path endpoint.'); return; }
    remember(); state[key] = ids[0]; state.pathNodeIds.clear(); state.pathEdgeIds.clear();
    applyPresentation({message:`Path ${key === 'sourceId' ? 'source' : 'target'} set to ${nameFor(ids[0])}`});
  };
  const shortestPath = () => {
    if (!state.sourceId || !state.targetId || state.sourceId === state.targetId) {
      statusText('Choose two different path endpoints.'); return;
    }
    remember();
    const queue = [state.sourceId]; const visited = new Set(queue); const parent = new Map();
    while (queue.length && !visited.has(state.targetId)) {
      const current = queue.shift();
      cy.edges().forEach((edge) => {
        if (!relationshipMatches(edge, {forTraversal:true})) return;
        const [source, target] = edgeEndpoints(edge);
        const next = source === current ? target : target === current ? source : null;
        if (next && !visited.has(next)) { visited.add(next); parent.set(next, {node:current, edge:edge.id()}); queue.push(next); }
      });
    }
    state.pathNodeIds.clear(); state.pathEdgeIds.clear();
    if (!visited.has(state.targetId)) { applyPresentation({message:'No path found in the accepted relationship scope.'}); return; }
    let cursor = state.targetId; state.pathNodeIds.add(cursor);
    while (cursor !== state.sourceId) { const step = parent.get(cursor); state.pathEdgeIds.add(step.edge); cursor = step.node; state.pathNodeIds.add(cursor); }
    applyPresentation({fit:true, message:`Shortest path · ${state.pathEdgeIds.size} relationships`});
  };

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
  })[character]);
  const runLayout = (name) => {
    remember(); controls.layout.value = name;
    const layout = cy.layout(layoutOptions(name));
    layout.one('layoutstop', () => { applyPresentation(); persist(); }); layout.run();
  };

  cy.on('tap', 'node', (event) => {
    const original = event.originalEvent || {};
    if (!(original.ctrlKey || original.metaKey || original.shiftKey)) {
      cy.nodes(':selected').not(event.target).unselect(); event.target.select();
    }
    renderInspector(); applyPresentation();
  });
  cy.on('tap', 'edge', (event) => renderInspector(event.target));
  cy.on('tap', (event) => {
    controls.context.hidden = true;
    if (event.target === cy) { cy.elements().unselect(); renderInspector(); applyPresentation(); }
  });
  cy.on('select unselect', 'node', () => { renderInspector(); updatePathLabels(); });
  cy.on('cxttap', 'node', (event) => {
    state.contextId = event.target.id();
    const position = event.renderedPosition || {x:20, y:20};
    const shell = byId('canvas-shell').getBoundingClientRect();
    controls.context.style.left = `${Math.min(position.x + 8, shell.width - 230)}px`;
    controls.context.style.top = `${Math.min(position.y + 8, shell.height - 290)}px`;
    controls.context.hidden = false; controls.context.querySelector('button')?.focus();
  });
  cy.on('pan zoom dragfree', () => {
    controls.zoom.value = Math.round(cy.zoom() * 100);
    controls.zoomValue.textContent = `${Math.round(cy.zoom() * 100)}%`;
    if (!state.restoring) persist();
  });

  controls.context.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]'); if (!button || !state.contextId) return;
    cy.elements().unselect(); const node = cy.getElementById(state.contextId); node.select();
    controls.context.hidden = true;
    const action = button.dataset.action;
    if (action === 'center') cy.animate({center:{eles:node}, zoom:Math.max(cy.zoom(), 0.8), duration:220});
    if (action === 'focus') focusSelection(1);
    if (action === 'expand') { remember(); state.focusIds = neighborhood([state.contextId], 2); applyPresentation({fit:true}); }
    if (action === 'hide') hideSelection();
    if (action === 'source') markEndpoint('sourceId');
    if (action === 'target') markEndpoint('targetId');
  });
  controls.search.addEventListener('input', () => refreshSearch(0));
  controls.search.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); refreshSearch(event.shiftKey ? -1 : 1); }
  });
  byId('search-prev').addEventListener('click', () => refreshSearch(-1));
  byId('search-next').addEventListener('click', () => refreshSearch(1));
  [controls.type, controls.status, controls.relationship, controls.direction].forEach((control) =>
    control.addEventListener('change', () => { remember(); applyPresentation({fit:true}); }));
  controls.confidence.addEventListener('change', () => { remember(); applyPresentation({fit:true}); });
  controls.confidence.addEventListener('input', () => { controls.confidenceValue.textContent = `${controls.confidence.value}%`; });
  controls.layout.addEventListener('change', (event) => runLayout(event.target.value));
  byId('zoom-out').addEventListener('click', () => cy.zoom({level:Math.max(0.05, cy.zoom() / 1.25), renderedPosition:{x:cy.width()/2, y:cy.height()/2}}));
  byId('zoom-in').addEventListener('click', () => cy.zoom({level:Math.min(4, cy.zoom() * 1.25), renderedPosition:{x:cy.width()/2, y:cy.height()/2}}));
  controls.zoom.addEventListener('input', () => cy.zoom({level:Number(controls.zoom.value)/100, renderedPosition:{x:cy.width()/2, y:cy.height()/2}}));
  byId('fit').addEventListener('click', fitReadable);
  byId('fullscreen').addEventListener('click', async () => {
    if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); else await document.exitFullscreen();
    setTimeout(() => { cy.resize(); fitReadable(); }, 80);
  });
  byId('toggle-inspector').addEventListener('click', (event) => {
    controls.main.classList.toggle('inspector-hidden');
    event.currentTarget.setAttribute('aria-expanded', String(!controls.main.classList.contains('inspector-hidden')));
    cy.resize(); persist();
  });
  byId('back').addEventListener('click', () => {
    if (!state.history.length) return; state.future.push(snapshot()); restore(state.history.pop());
    byId('back').disabled = state.history.length === 0; byId('forward').disabled = false;
  });
  byId('forward').addEventListener('click', () => {
    if (!state.future.length) return; state.history.push(snapshot()); restore(state.future.pop());
    byId('back').disabled = false; byId('forward').disabled = state.future.length === 0;
  });
  document.querySelectorAll('[data-focus-depth]').forEach((button) =>
    button.addEventListener('click', () => focusSelection(Number(button.dataset.focusDepth))));
  byId('hide-selection').addEventListener('click', hideSelection);
  byId('reset-view').addEventListener('click', resetView);
  byId('mark-source').addEventListener('click', () => markEndpoint('sourceId'));
  byId('mark-target').addEventListener('click', () => markEndpoint('targetId'));
  byId('find-path').addEventListener('click', shortestPath);
  byId('clear-path').addEventListener('click', () => {
    remember(); state.pathNodeIds.clear(); state.pathEdgeIds.clear(); state.sourceId = null; state.targetId = null; applyPresentation();
  });
  byId('open-table').addEventListener('click', () => byId('table-dialog').showModal());
  byId('close-table').addEventListener('click', () => byId('table-dialog').close());
  addEventListener('resize', () => cy.resize());
  addEventListener('keydown', (event) => {
    if (event.key === '/' && !isTyping(event.target)) { event.preventDefault(); controls.search.focus(); return; }
    if (event.key === 'Escape') { controls.context.hidden = true; controls.search.value = ''; refreshSearch(); return; }
    if (isTyping(event.target)) return;
    const pan = 70;
    if (event.key === 'ArrowLeft') cy.panBy({x:pan, y:0});
    else if (event.key === 'ArrowRight') cy.panBy({x:-pan, y:0});
    else if (event.key === 'ArrowUp') cy.panBy({x:0, y:pan});
    else if (event.key === 'ArrowDown') cy.panBy({x:0, y:-pan});
    else if (event.key === '+' || event.key === '=') byId('zoom-in').click();
    else if (event.key === '-') byId('zoom-out').click();
    else if (event.key === '0') byId('fit').click();
    else return;
    event.preventDefault();
  });

  const saved = loadSaved();
  if (saved?.positions) {
    cy.nodes().positions((node) => saved.positions[node.id()] || node.position()); restore(saved);
  } else {
    const layout = cy.layout(layoutOptions(cy.edges().length ? 'cose' : 'grid'));
    layout.one('layoutstop', () => { applyPresentation(); fitReadable(); persist(); }); layout.run();
  }
  controls.zoom.value = Math.round(cy.zoom() * 100);
  controls.zoomValue.textContent = `${Math.round(cy.zoom() * 100)}%`;
  updatePathLabels(); renderInspector(); updateAccessibleTable();
})();
"""


def render_graph_explorer(
    *,
    title: str,
    generated: str,
    investigation_id: str,
    run_id: str,
    elements_json: str,
    entity_types: tuple[str, ...],
    relationship_types: tuple[str, ...],
    entity_count: int,
    relationship_count: int,
    fallback_rows: str,
) -> str:
    """Render one offline-capable graph workspace document."""
    safe_title = html.escape(title)
    type_options = "".join(
        f'<option value="{html.escape(value)}">{html.escape(value.title())}</option>'
        for value in entity_types
    )
    relationship_options = "".join(
        f'<option value="{html.escape(value)}">{html.escape(value.title())}</option>'
        for value in relationship_types
    )
    storage_key = json.dumps(
        f"raven.graph.viewport.v1.{investigation_id}.{run_id}", ensure_ascii=False
    )
    script = _SCRIPT.replace("__RAVEN_ELEMENTS__", elements_json).replace(
        "__RAVEN_STORAGE_KEY__", storage_key
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Raven graph · {safe_title}</title>
  <style>{_STYLE}</style>
  <script src="https://cdn.jsdelivr.net/npm/cytoscape@3.34.2/dist/cytoscape.min.js"></script>
</head>
<body>
  <header>
    <div class="toolbar">
      <div class="heading"><h1>{safe_title}</h1><div class="meta">{entity_count} entities · {relationship_count} relationships · {html.escape(generated)}</div></div>
      <div class="search-group">
        <input id="search" placeholder="Find entity or relationship…" aria-label="Search graph">
        <button id="search-prev" title="Previous match" aria-label="Previous search match">‹</button>
        <output id="search-count" aria-live="polite">—</output>
        <button id="search-next" title="Next match" aria-label="Next search match">›</button>
      </div>
      <div class="viewport-controls" role="group" aria-label="Graph zoom controls">
        <button id="zoom-out" title="Zoom out" aria-label="Zoom out">−</button>
        <input id="zoom" type="range" min="5" max="400" step="5" value="100" aria-label="Zoom level">
        <output id="zoom-value">100%</output>
        <button id="zoom-in" title="Zoom in" aria-label="Zoom in">＋</button>
        <button id="fit">Fit</button><button id="fullscreen">Fullscreen</button>
        <button id="toggle-inspector" aria-expanded="true">Details</button>
      </div>
    </div>
    <div class="toolbar">
      <div class="filter-controls" aria-label="Graph filters">
        <select id="type" aria-label="Entity type"><option value="">All entity types</option>{type_options}</select>
        <select id="status" aria-label="Review state"><option value="">All states</option><option value="proposed">Proposed</option><option value="verified">Verified</option><option value="rejected">Rejected</option><option value="archived">Archived</option></select>
        <select id="relationship" aria-label="Relationship type"><option value="">All relationships</option>{relationship_options}</select>
        <select id="direction" aria-label="Relationship direction"><option value="">All directions</option><option value="outgoing">Outgoing</option><option value="incoming">Incoming</option><option value="bidirectional">Bidirectional</option></select>
        <label class="confidence">Confidence <input id="confidence" type="range" min="0" max="100" step="5" value="0"><output id="confidence-value">0%</output></label>
        <select id="layout" aria-label="Graph layout"><option value="cose">CoSE</option><option value="breadthfirst">Hierarchy</option><option value="concentric">Concentric</option><option value="circle">Circle</option><option value="grid">Grid</option></select>
      </div>
      <span class="help">/ search · arrows pan · +/− zoom · 0 fit</span>
    </div>
  </header>
  <div id="scope-status" class="scope-status" role="status" aria-live="polite">Preparing graph…</div>
  <main id="workspace">
    <section id="canvas-shell" class="canvas-shell" aria-label="Interactive graph workspace">
      <div id="cy" tabindex="0" role="application" aria-label="Graph; use arrows to pan, plus or minus to zoom, zero to fit"></div>
      <div id="empty-state" class="empty-state" hidden>No entities match the current view.</div>
      <nav id="context-menu" class="context-menu" aria-label="Entity actions" hidden>
        <button data-action="center">Center entity</button><button data-action="focus">Focus 1-hop neighborhood</button>
        <button data-action="expand">Expand visible neighborhood</button><button data-action="hide">Hide from view</button>
        <button data-action="source">Use as path source</button><button data-action="target">Use as path target</button>
      </nav>
    </section>
    <aside><h2>SELECTION INSPECTOR</h2><div id="inspector"></div></aside>
  </main>
  <footer>
    <div class="action-controls">
      <button id="back" disabled title="Previous graph view">← Back</button><button id="forward" disabled title="Next graph view">Forward →</button>
      <span class="divider"></span><span>Focus</span><button data-focus-depth="1">1 hop</button><button data-focus-depth="2">2 hops</button><button data-focus-depth="3">3 hops</button>
      <button id="hide-selection">Hide</button><button id="reset-view">Reset all</button><button id="open-table">Table</button>
    </div>
    <div class="path-controls">
      <span id="path-source" class="path-label"><strong>A</strong> —</span><button id="mark-source">Set A</button>
      <span id="path-target" class="path-label"><strong>B</strong> —</span><button id="mark-target">Set B</button>
      <button id="find-path" class="primary">Find path</button><button id="clear-path">Clear</button>
    </div>
  </footer>
  <div id="fallback"><div class="error">Interactive renderer unavailable. The relationship table remains usable.</div>
    <table><thead><tr><th>Source</th><th>Relation</th><th>Target</th><th>Confidence</th><th>Status</th></tr></thead><tbody>{fallback_rows}</tbody></table></div>
  <dialog id="table-dialog"><div class="dialog-header"><h2>ACCESSIBLE GRAPH TABLE</h2><button id="close-table">Close</button></div>
    <div class="dialog-body"><table><thead><tr><th>Kind</th><th>Source / entity</th><th>Relation / type</th><th>Target</th><th>Confidence</th><th>Status</th></tr></thead><tbody id="graph-table-body"></tbody></table></div></dialog>
  <script>{script}</script>
</body>
</html>"""
