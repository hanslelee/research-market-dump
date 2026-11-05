/* MathBridge market evidence viewer (research-market-dump).
 * Reads market/out/viewer.json (built by `python market/run.py export`).
 * Not connected: the copy published with this page (GitHub Pages). Connected: the repository itself, through the
 * GitHub API with your token; then reviews and conclusions are saved as one commit together with an "export" request,
 * and GitHub Actions rebuilds viewer.json and the workbook (about 1 to 2 minutes).
 */
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const VIEW_PATH = 'market/out/viewer.json';
  const WORKBOOK = 'market/out/01_Hansle_Market_Research.xlsx';
  const KINDS = {
    paper: { label: 'Paper', shape: 'ellipse' }, news: { label: 'News', shape: 'diamond' },
    government: { label: 'Government statistics', shape: 'hexagon' }, company: { label: 'Company page', shape: 'rectangle' },
    report: { label: 'Research report', shape: 'triangle' }, book: { label: 'Book', shape: 'barrel' }, other: { label: 'Other', shape: 'star' },
  };
  const STATUSES = ['UNVERIFIED', 'PARTIAL', 'VERIFIED', 'NOT APPLICABLE'];
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const statusClass = s => (s === 'NOT APPLICABLE' ? 'NA' : s);
  const badge = (s, extra = '') => `<span class="badge ${esc(statusClass(s))} ${extra}">${esc(s)}</span>`;
  const today = () => new Date().toISOString().slice(0, 10);

  const state = { data: null, tab: 'home', conn: null, cy: null, kinds: new Set(Object.keys(KINDS)), selEv: null, pending: null };

  // ---------- connection ----------
  const CONN_KEY = 'rmd.conn';
  try { state.conn = JSON.parse(localStorage.getItem(CONN_KEY) || 'null'); } catch { state.conn = null; }
  const publicRepo = () => {
    const owner = location.hostname.endsWith('.github.io') ? location.hostname.split('.')[0] : 'hanslelee';
    return `${owner}/${location.pathname.split('/').filter(Boolean)[0] || 'research-market-dump'}`;
  };
  const repo = () => state.conn?.repo || publicRepo();
  const branch = () => state.conn?.branch || 'main';

  const api = {
    headers(extra = {}) {
      const h = { 'X-GitHub-Api-Version': '2022-11-28', ...extra };
      if (state.conn?.token) h.Authorization = `Bearer ${state.conn.token}`;
      return h;
    },
    async call(method, path, body) {
      const r = await fetch(`https://api.github.com/repos/${repo()}${path}`, {
        method, headers: this.headers(body ? { 'Content-Type': 'application/json' } : {}), body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
      if (!r.ok) { const e = new Error(`GitHub ${r.status}`); e.status = r.status; throw e; }
      return r.status === 204 ? null : r.json();
    },
    async raw(path, as = 'json') {
      const r = await fetch(`https://api.github.com/repos/${repo()}/contents/${path}?ref=${encodeURIComponent(branch())}`,
        { headers: this.headers({ Accept: 'application/vnd.github.raw+json' }), cache: 'no-store' });
      if (!r.ok) { const e = new Error(`${path}: GitHub ${r.status}`); e.status = r.status; throw e; }
      return as === 'blob' ? r.blob() : as === 'text' ? r.text() : r.json();
    },
    // one commit for several text files (Git Data API); retries once if the branch moved
    async commit(files, message) {
      for (let attempt = 0; attempt < 2; attempt++) {
        const ref = await this.call('GET', `/git/ref/heads/${encodeURIComponent(branch())}`);
        const head = await this.call('GET', `/git/commits/${ref.object.sha}`);
        const tree = await this.call('POST', '/git/trees', { base_tree: head.tree.sha,
          tree: files.map(f => ({ path: f.path, mode: '100644', type: 'blob', content: f.content })) });
        const c = await this.call('POST', '/git/commits', { message, tree: tree.sha, parents: [ref.object.sha] });
        try { await this.call('PATCH', `/git/refs/heads/${encodeURIComponent(branch())}`, { sha: c.sha }); return; }
        catch (e) { if (e.status !== 422 || attempt === 1) throw e; }
      }
    },
  };

  function toast(msg, err = false) {
    const t = $('#toast');
    t.textContent = msg; t.className = 'toast' + (err ? ' err' : ''); t.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, err ? 7000 : 4000);
  }

  // ---------- load ----------
  async function load() {
    try {
      state.data = state.conn?.token ? await api.raw(VIEW_PATH)
        : await (await fetch(`../${VIEW_PATH}?t=${Date.now()}`, { cache: 'no-store' })).json();
    } catch (e) {
      $('#banner').hidden = false;
      $('#banner').textContent = `Could not load data (${e.message}). Check that market/out/viewer.json exists.`;
      return;
    }
    const d = state.data;
    d.evById = new Map(d.evidence.map(e => [e.id, e]));
    d.claimById = new Map(d.claims.map(c => [c.id, c]));
    $('#case').textContent = `${d.case_id || ''} ${d.version || ''}`;
    $('#generated').textContent = `Updated ${new Date(d.generated_at).toLocaleString()}`;
    $('#repo-link').href = `https://github.com/${repo()}`;
    $('#btn-connect').textContent = state.conn?.token ? `Connected: ${state.conn.repo}` : 'Connect repository';
    const unrev = d.evidence.filter(e => e.status === 'UNVERIFIED').length;
    $('#banner').hidden = !unrev;
    $('#banner').textContent = unrev ? `${unrev} evidence row(s) not reviewed yet: open them in the Evidences tab and mark PARTIAL / VERIFIED / NOT APPLICABLE. Unreviewed evidence does not count toward claim status.` : '';
    fillFilters();
    render();
  }

  function render() {
    for (const t of ['home', 'evidences', 'claims']) $(`#view-${t}`).hidden = state.tab !== t;
    for (const b of document.querySelectorAll('#tabs button')) b.classList.toggle('on', b.dataset.tab === state.tab);
    if (!state.data) return;
    if (state.tab === 'home') renderHome();
    if (state.tab === 'evidences') renderEvidences();
    if (state.tab === 'claims') renderClaims();
  }

  // ---------- home ----------
  function visibleEvidence() {
    const hideU = $('#hide-unverified').checked, hideE = $('#hide-edu').checked, hideN = $('#hide-na').checked;
    return state.data.evidence.filter(e => state.kinds.has(e.kind) && !(hideU && e.status === 'UNVERIFIED')
      && !(hideE && e.edu_related) && !(hideN && e.status === 'NOT APPLICABLE'));
  }

  function renderHome() {
    const d = state.data;
    $('#home-claims').innerHTML = d.claims.filter(c => c.role === 'parent').map(c => `
      <div class="home-claim" data-claim="${esc(c.id)}">
        <div class="row"><b>${esc(c.id)}</b>${badge(c.status)}${badge(c.action)}</div>
        <div>${esc(c.text)}</div>
      </div>`).join('');
    const counts = Object.fromEntries(Object.keys(KINDS).map(k => [k, d.evidence.filter(e => e.kind === k).length]));
    $('#kind-filters').innerHTML = Object.entries(KINDS).map(([k, v]) => `
      <label><input type="checkbox" data-kind="${k}" ${state.kinds.has(k) ? 'checked' : ''}><i class="shape ${k}"></i>${v.label} <span class="meta">${counts[k]}</span></label>`).join('');
    drawGraph();
  }

  function drawGraph() {
    if (typeof cytoscape === 'undefined') { $('#graph').innerHTML = '<p class="hint" style="padding:16px">Could not load the graph library.</p>'; return; }
    const d = state.data, ev = visibleEvidence();
    const statusColor = s => css(`--${statusClass(s) === 'NA' ? 'NA' : statusClass(s)}`) || css('--UNVERIFIED');
    const nodes = d.claims.map(c => ({ data: { id: c.id, label: c.id, kind: c.role, color: statusColor(c.status) } }));
    const edges = d.claims.filter(c => c.role === 'sub' && c.parent).map(c => ({ data: { id: `${c.id}>${c.parent}`, source: c.id, target: c.parent, kind: 'tree' } }));
    for (const e of ev) {
      if (!d.claimById.has(e.claim)) continue;
      nodes.push({ data: { id: e.id, label: e.id, kind: 'evidence', shape: KINDS[e.kind]?.shape || 'star',
        color: css(`--k-${e.kind}`) || css('--k-other'), faded: e.status === 'UNVERIFIED' || e.status === 'NOT APPLICABLE' ? 1 : 0 } });
      edges.push({ data: { id: `${e.id}>${e.claim}`, source: e.id, target: e.claim, kind: 'ev', stance: e.stance,
        color: css(`--${e.stance}`) || css('--quiet'), dashed: e.status === 'UNVERIFIED' ? 1 : 0 } });
    }
    const ink = css('--ink'), line = css('--line');
    if (state.cy) state.cy.destroy();
    state.cy = cytoscape({
      container: $('#graph'), elements: { nodes, edges }, wheelSensitivity: 0.3,
      style: [
        { selector: 'node', style: { label: 'data(label)', 'font-size': 9, color: ink, 'text-valign': 'bottom', 'text-margin-y': 3 } },
        { selector: 'node[kind="parent"]', style: { shape: 'round-rectangle', width: 92, height: 40, 'background-color': 'data(color)',
          'font-size': 13, 'font-weight': 700, color: '#fff', 'text-valign': 'center', 'text-margin-y': 0 } },
        { selector: 'node[kind="sub"]', style: { shape: 'round-rectangle', width: 74, height: 28, 'background-color': css('--surface'),
          'border-width': 3, 'border-color': 'data(color)', 'font-size': 11, 'font-weight': 600, 'text-valign': 'center', 'text-margin-y': 0 } },
        { selector: 'node[kind="evidence"]', style: { shape: 'data(shape)', width: 18, height: 18, 'background-color': 'data(color)' } },
        { selector: 'node[faded=1]', style: { opacity: 0.45 } },
        { selector: 'edge', style: { width: 2, 'curve-style': 'bezier', 'line-color': line } },
        { selector: 'edge[kind="tree"]', style: { width: 3, 'line-color': css('--quiet'), 'target-arrow-shape': 'triangle', 'target-arrow-color': css('--quiet') } },
        { selector: 'edge[kind="ev"]', style: { 'line-color': 'data(color)', 'target-arrow-shape': 'triangle', 'target-arrow-color': 'data(color)', 'arrow-scale': 0.8 } },
        { selector: 'edge[dashed=1]', style: { 'line-style': 'dashed' } },
        { selector: ':selected', style: { 'border-width': 3, 'border-color': css('--accent') } },
      ],
      layout: { name: 'cose', animate: false, nodeRepulsion: () => 9000, idealEdgeLength: e => (e.data('kind') === 'tree' ? 90 : 60), padding: 24 },
    });
    state.cy.on('tap', 'node', e => {
      const id = e.target.id();
      $('#home-detail').innerHTML = state.data.evById.has(id) ? evidenceDetail(state.data.evById.get(id)) : claimDetail(state.data.claimById.get(id));
    });
  }

  // ---------- evidences ----------
  function fillFilters() {
    const d = state.data;
    const opt = (sel, values, label = v => v) => {
      const cur = $(sel).value, first = $(sel).options[0].outerHTML;
      $(sel).innerHTML = first + values.map(v => `<option value="${esc(v)}">${esc(label(v))}</option>`).join('');
      $(sel).value = cur;
    };
    opt('#ev-kind', Object.keys(KINDS).filter(k => d.evidence.some(e => e.kind === k)), k => KINDS[k].label);
    opt('#ev-claim', d.claims.filter(c => c.role === 'sub').map(c => c.id));
    opt('#ev-status', STATUSES);
  }

  function filteredEvidence() {
    const q = $('#ev-search').value.trim().toLowerCase();
    const k = $('#ev-kind').value, c = $('#ev-claim').value, s = $('#ev-status').value, st = $('#ev-stance').value;
    return state.data.evidence.filter(e => (!k || e.kind === k) && (!c || e.claim === c) && (!s || e.status === s) && (!st || e.stance === st)
      && (!q || [e.title, e.quote, e.publisher, e.finding, e.id].join(' ').toLowerCase().includes(q)))
      .sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
  }

  function renderEvidences() {
    const rows = filteredEvidence();
    $('#ev-count').textContent = `${rows.length} / ${state.data.evidence.length}`;
    $('#ev-table tbody').innerHTML = rows.map(e => `
      <tr data-ev="${esc(e.id)}" class="${e.id === state.selEv ? 'sel' : ''} ${e.status === 'NOT APPLICABLE' ? 'na' : ''}">
        <td>${esc(e.id)}</td>
        <td><i class="shape ${esc(e.kind)}" title="${esc(KINDS[e.kind]?.label || e.kind)}"></i></td>
        <td class="src"><b>${esc(e.title || e.url)}</b><span>${esc(e.publisher)}${e.date ? ' · ' + esc(e.date) : ''}</span></td>
        <td>${e.edu_related ? '<span class="badge outline">EDU related</span> ' : ''}${esc(e.claim)}</td>
        <td><span class="stance ${esc(e.stance)}">${esc(e.stance)}</span></td>
        <td>${badge(e.status)}</td>
        <td class="meta">${esc(e.checked_by)} ${esc(e.checked_date)}</td>
      </tr>`).join('');
  }

  const snapshotLink = e => e.snapshot ? `https://github.com/${repo()}/blob/${branch()}/${e.snapshot}` : '';

  function evidenceDetail(e) {
    if (!e) return '';
    const c = state.data.claimById.get(e.claim);
    const weak = ['excerpt', 'abstract', 'none', ''].includes(e.snapshot_kind);
    return `
      <div class="meta"><i class="shape ${esc(e.kind)}"></i> ${esc(KINDS[e.kind]?.label || e.kind)} · ${esc(e.id)} · ${esc(e.found_by)}</div>
      <h3>${esc(e.title || e.url)}</h3>
      <div>${badge(e.status)} <span class="stance ${esc(e.stance)}">${esc(e.stance)}</span>${e.stance_by_agent ? ` <span class="meta">(agent said: ${esc(e.stance_by_agent)})</span>` : ''}
        ${e.edu_related ? ' <span class="badge outline">EDU related</span>' : ''}</div>
      <div class="field"><b>Claim</b>${esc(e.claim)} ${c ? '· ' + esc(c.text) : ''}</div>
      <div class="field"><b>Quote (copied verbatim)</b><blockquote>${esc(e.quote)}</blockquote></div>
      ${state.conn?.token ? `<div class="field" data-edit="${esc(e.id)}"><b>Finding</b><textarea data-field="finding">${esc(e.finding)}</textarea>
        <b style="margin-top:8px">Limitation</b><textarea data-field="limitation">${esc(e.limitation)}</textarea>
        <div class="actions"><button type="button" data-save-text>Save finding and limitation</button>
        ${e.edited_by ? `<span class="meta">edited by ${esc(e.edited_by)} ${esc(e.edited_date)}</span>` : ''}</div></div>`
      : `<div class="field"><b>Finding</b>${esc(e.finding)}</div>
      <div class="field"><b>Limitation</b>${esc(e.limitation)}</div>`}
      <div class="field"><b>Source</b>${esc(e.publisher)} ${esc(e.date)}<br>
        ${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">Open original</a>` : ''}
        ${snapshotLink(e) ? ` · <a href="${esc(snapshotLink(e))}" target="_blank" rel="noopener">Saved copy (${esc(e.snapshot_kind)})</a>` : ''}</div>
      ${e.checked_by ? `<div class="field"><b>Checked</b>${esc(e.checked_by)} ${esc(e.checked_date)}</div>` : ''}
      ${reviewBox(e, weak)}`;
  }

  function reviewBox(e, weak) {
    if (!state.conn?.token) return `<div class="review hint">Click "Connect repository" above to review.</div>`;
    return `
      <div class="review" data-review="${esc(e.id)}">
        <b>Review</b>
        <p class="hint">Open the original, check the quote is there, then choose. Claim status and the workbook update 1 to 2 minutes after saving.</p>
        <ul class="hint" style="margin:4px 0 8px;padding-left:18px">
          <li><b>PARTIAL</b>: the evidence backs only part of the claim (indirect, conditional, another setting or country)</li>
          <li><b>VERIFIED</b>: the evidence backs the claim fully</li>
          <li><b>NOT APPLICABLE</b>: wrong or unrelated to this claim (excluded)</li>
        </ul>
        ${weak ? '<p class="warn">The saved copy is an excerpt or abstract. Use "Open original" to check the quote first.</p>' : ''}
        <input data-field="note" placeholder="Note (optional)" style="width:100%">
        <details style="margin-top:6px"><summary class="meta">Only if the stance (supports/contradicts) is wrong</summary>
          <select data-field="stance">${['supports', 'contradicts'].map(s => `<option ${s === e.stance ? 'selected' : ''}>${s}</option>`).join('')}</select>
        </details>
        <div class="actions">
          <button type="button" data-set="PARTIAL">PARTIAL</button>
          <button type="button" data-set="VERIFIED">VERIFIED</button>
          <button type="button" data-set="NOT APPLICABLE">NOT APPLICABLE</button>
          <button type="button" data-set="UNVERIFIED" class="quiet">Undo</button>
        </div>
      </div>`;
  }

  // ---------- claims ----------
  function chip(id, kind = '') {
    const e = state.data.evById.get(id);
    const cls = e ? `${e.stance === 'contradicts' ? 'contradicts' : ''} ${e.status === 'UNVERIFIED' ? 'unverified' : ''}` : 'unverified';
    return `<span class="chip ${cls} ${kind}" data-ev="${esc(id)}" title="${esc(e ? `${e.status} · ${e.title}` : 'other member\'s file')}">${esc(id)}</span>`;
  }

  function claimDetail(c) {
    if (!c) return '';
    const subs = state.data.claims.filter(s => s.parent === c.id);
    return `
      <div class="meta">${c.role === 'parent' ? 'Team claim' : `Sub-claim of ${esc(c.parent)}`}</div>
      <h3>${esc(c.id)} ${esc(c.text)}</h3>
      <div>${badge(c.status)} ${badge(c.action)}</div>
      ${c.conclusion ? `<div class="field"><b>Conclusion</b>${esc(c.conclusion)}</div>` : ''}
      <div class="field"><b>Limitation</b>${esc(c.limitation)}</div>
      ${subs.length ? `<div class="field"><b>Sub-claims</b>${subs.map(s => `<div>${esc(s.id)} ${badge(s.status)}</div>`).join('')}</div>` : ''}
      ${c.supporting?.length ? `<div class="field"><b>Supporting evidence</b><div class="chips">${c.supporting.map(i => chip(i)).join('')}</div></div>` : ''}
      ${c.counter?.length ? `<div class="field"><b>Counter-evidence</b><div class="chips">${c.counter.map(i => chip(i)).join('')}</div></div>` : ''}
      ${c.basis ? `<div class="field"><b>Basis</b>${esc(c.basis)}</div>` : ''}`;
  }

  function renderClaims() {
    const d = state.data;
    $('#claims-list').innerHTML = d.claims.filter(c => c.role === 'parent').map(p => `
      <article class="parent">
        <header><h2>${esc(p.id)}</h2>${badge(p.status)}${badge(p.action)}<span class="meta">${esc(p.review_status)}</span></header>
        <p>${esc(p.text)}</p>
        <p class="meta">${esc(p.limitation)}</p>
        ${state.conn?.token ? `
          <textarea data-conclusion="${esc(p.id)}" placeholder="Your conclusion for the team claim (goes into Market Conclusions and market_handoff.json)">${esc(p.conclusion || '')}</textarea>
          <div class="actions" style="margin-top:6px"><button type="button" data-save-conclusion="${esc(p.id)}">Save team-claim conclusion</button></div>`
          : (p.conclusion ? `<p><b>Conclusion:</b> ${esc(p.conclusion)}</p>` : '')}
        ${d.claims.filter(s => s.parent === p.id).map(s => `
          <div class="sub">
            <header><b>${esc(s.id)}</b>${badge(s.status)}${badge(s.action)}${s.fixed_status ? '<span class="badge outline">fixed by design</span>' : ''}</header>
            <p>${esc(s.text)}</p>
            ${s.supporting.length ? `<div class="meta">Supporting</div><div class="chips">${s.supporting.map(i => chip(i)).join('')}</div>` : ''}
            ${s.counter.length ? `<div class="meta">Counter</div><div class="chips">${s.counter.map(i => chip(i)).join('')}</div>` : ''}
            <p class="meta">${esc(s.limitation)}</p>
            ${state.conn?.token ? `
              <textarea data-conclusion="${esc(s.id)}" placeholder="Your conclusion for this sub-claim (goes into the Market Conclusions sheet)">${esc(s.conclusion)}</textarea>
              <div class="actions" style="margin-top:6px"><button type="button" data-save-conclusion="${esc(s.id)}">Save conclusion</button></div>`
              : (s.conclusion ? `<p><b>Conclusion:</b> ${esc(s.conclusion)}</p>` : '')}
          </div>`).join('')}
      </article>`).join('');
  }

  // ---------- saving (one commit + export request) ----------
  function csvParse(text) {
    const rows = []; let row = [], f = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) { if (ch === '"' && text[i + 1] === '"') { f += '"'; i++; } else if (ch === '"') q = false; else f += ch; }
      else if (ch === '"') q = true; else if (ch === ',') { row.push(f); f = ''; }
      else if (ch === '\n' || ch === '\r') { if (ch === '\r' && text[i + 1] === '\n') i++; row.push(f); rows.push(row); row = []; f = ''; }
      else f += ch;
    }
    if (f || row.length) { row.push(f); rows.push(row); }
    return rows.filter(r => r.some(x => x !== ''));
  }
  const csvCell = v => /[",\n]/.test(v) ? `"${String(v).replace(/"/g, '""')}"` : String(v);

  function exportRequest() {
    const id = `req-${Date.now().toString(36)}`;
    return { id, file: { path: `requests/${id}.json`, content: JSON.stringify({ id, kind: 'export', status: 'pending', created_at: today(),
      requested_at: new Date().toISOString() }, null, 2) + '\n' } };
  }

  async function saveWithExport(files, message) {
    const req = exportRequest();
    await api.commit([...files, req.file], message);
    state.pending = req.id;
    toast('Saved. The page refreshes when claim status and the workbook are rebuilt (1 to 2 minutes).');
    watch();
  }

  async function saveReview(id, status, stance, note) {
    const text = await api.raw('market/review.csv', 'text').catch(() => 'evidence_id,verification_status,checked_by,checked_date,note,stance\n');
    const rows = csvParse(text);
    const header = rows[0] || ['evidence_id', 'verification_status', 'checked_by', 'checked_date', 'note', 'stance'];
    if (!header.includes('stance')) header.push('stance');
    const idx = Object.fromEntries(header.map((h, i) => [h, i]));
    const body = rows.slice(1).filter(r => r[idx.evidence_id] !== id);
    if (status !== 'UNVERIFIED') {
      const r = header.map(() => '');
      r[idx.evidence_id] = id; r[idx.verification_status] = status; r[idx.checked_by] = state.conn.name || 'Hansle';
      r[idx.checked_date] = today(); r[idx.note] = note || ''; r[idx.stance] = stance || '';
      body.push(r);
    }
    const out = [header, ...body].map(r => r.map(csvCell).join(',')).join('\n') + '\n';
    await saveWithExport([{ path: 'market/review.csv', content: out }], `Review ${id}: ${status}`);
    const e = state.data.evById.get(id);  // show it right away; the rebuilt file replaces it shortly
    if (e) { e.status = status; e.stance = stance || e.stance; e.checked_by = status === 'UNVERIFIED' ? '' : (state.conn.name || 'Hansle'); e.checked_date = today(); }
    render();
  }

  async function saveText(id, finding, limitation) {
    const cur = await api.raw('market/edits.json').catch(() => ({}));
    cur[id] = { finding, limitation, by: state.conn.name || 'Hansle', date: today() };
    await saveWithExport([{ path: 'market/edits.json', content: JSON.stringify(cur, null, 2) + '\n' }], `Edit text ${id}`);
    const e = state.data.evById.get(id);
    if (e) Object.assign(e, { finding, limitation, edited_by: cur[id].by, edited_date: cur[id].date });
  }

  async function saveConclusion(id, text) {
    const cur = await api.raw('market/conclusions.json').catch(() => ({}));
    cur[id] = { ...(cur[id] || {}), conclusion: text };
    await saveWithExport([{ path: 'market/conclusions.json', content: JSON.stringify(cur, null, 2) + '\n' }], `Conclusion ${id}`);
  }

  function watch() {
    clearTimeout(watch.timer);
    watch.timer = setTimeout(async function tick() {
      if (!state.pending) return;
      try { await api.raw(`requests/${state.pending}.json`); watch.timer = setTimeout(tick, 15000); }
      catch (e) {
        if (e.status === 404) { state.pending = null; await load(); toast('Updated.'); }
        else watch.timer = setTimeout(tick, 15000);
      }
    }, 20000);
  }

  // ---------- events ----------
  $('#tabs').onclick = e => { const b = e.target.closest('button[data-tab]'); if (b) { state.tab = b.dataset.tab; render(); } };
  $('#kind-filters').onchange = e => { const k = e.target.dataset.kind; if (!k) return; e.target.checked ? state.kinds.add(k) : state.kinds.delete(k); drawGraph(); };
  for (const id of ['#hide-unverified', '#hide-edu', '#hide-na']) $(id).onchange = drawGraph;
  $('#home-claims').onclick = e => { const c = e.target.closest('[data-claim]'); if (c) { $('#home-detail').innerHTML = claimDetail(state.data.claimById.get(c.dataset.claim)); state.cy?.$id(c.dataset.claim).select(); } };
  for (const id of ['#ev-search', '#ev-kind', '#ev-claim', '#ev-status', '#ev-stance']) $(id).oninput = renderEvidences;
  $('#ev-table').onclick = e => {
    const tr = e.target.closest('tr[data-ev]'); if (!tr) return;
    state.selEv = tr.dataset.ev; $('#ev-detail').innerHTML = evidenceDetail(state.data.evById.get(state.selEv)); renderEvidences();
  };
  document.addEventListener('click', async e => {
    const chipEl = e.target.closest('.chip[data-ev]');
    if (chipEl) {
      const ev = state.data.evById.get(chipEl.dataset.ev);
      const target = state.tab === 'claims' ? '#claim-detail' : state.tab === 'home' ? '#home-detail' : '#ev-detail';
      $(target).innerHTML = ev ? evidenceDetail(ev) : `<p class="hint">${esc(chipEl.dataset.ev)} is an ID from another member's file; it is checked at integration.</p>`;
      return;
    }
    const set = e.target.closest('[data-set]');
    if (set) {
      const box = set.closest('[data-review]');
      set.disabled = true;
      const ev = state.data.evById.get(box.dataset.review), st = box.querySelector('[data-field=stance]').value;
      try { await saveReview(box.dataset.review, set.dataset.set, st !== ev?.stance ? st : '', box.querySelector('[data-field=note]').value); }
      catch (err) { toast(`Could not save: ${err.message}`, true); set.disabled = false; }
      return;
    }
    const stx = e.target.closest('[data-save-text]');
    if (stx) {
      const box = stx.closest('[data-edit]'); stx.disabled = true;
      try { await saveText(box.dataset.edit, box.querySelector('[data-field=finding]').value.trim(), box.querySelector('[data-field=limitation]').value.trim()); }
      catch (err) { toast(`Could not save: ${err.message}`, true); }
      stx.disabled = false;
      return;
    }
    const sc = e.target.closest('[data-save-conclusion]');
    if (sc) {
      const id = sc.dataset.saveConclusion; sc.disabled = true;
      try { await saveConclusion(id, document.querySelector(`[data-conclusion="${CSS.escape(id)}"]`).value.trim()); }
      catch (err) { toast(`Could not save: ${err.message}`, true); }
      sc.disabled = false;
    }
  });

  $('#btn-excel').onclick = async e => {
    const b = e.currentTarget; b.disabled = true;
    try {
      const blob = await api.raw(WORKBOOK, 'blob');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = `01_Hansle_Market_Research_${today()}.xlsx`;
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (err) { toast(`Could not download the workbook (${err.message}).`, true); }
    b.disabled = false;
  };
  $('#btn-rebuild').onclick = async e => {
    if (!state.conn?.token) { toast('Connect the repository to rebuild.', true); $('#connect-dialog').showModal(); return; }
    if (state.pending) { toast('A rebuild is already running.'); return; }
    const b = e.currentTarget; b.disabled = true;
    try { const req = exportRequest(); await api.commit([req.file], 'Request export'); state.pending = req.id;
      toast('Rebuild requested. It takes 1 to 2 minutes.'); watch(); }
    catch (err) { toast(`Could not send the request: ${err.message}`, true); }
    b.disabled = false;
  };

  $('#btn-connect').onclick = () => {
    const f = $('#connect-form');
    f.repo.value = state.conn?.repo || publicRepo(); f.branch.value = state.conn?.branch || 'main';
    f.token.value = state.conn?.token || ''; f.name.value = state.conn?.name || 'Hansle';
    $('#connect-dialog').showModal();
  };
  $('#connect-dialog').addEventListener('close', async () => {
    if ($('#connect-dialog').returnValue !== 'ok') return;
    const f = $('#connect-form');
    state.conn = { repo: f.repo.value.trim().replace(/^https:\/\/github\.com\//, '').replace(/\/$/, ''), branch: f.branch.value.trim() || 'main',
      token: f.token.value.trim(), name: f.name.value.trim() || 'Hansle' };
    try { localStorage.setItem(CONN_KEY, JSON.stringify(state.conn)); } catch { /* private window: this tab only */ }
    await load();
  });
  $('#btn-disconnect').onclick = async () => {
    state.conn = null; try { localStorage.removeItem(CONN_KEY); } catch { /* ignore */ }
    $('#connect-dialog').close(); await load();
  };

  load();
})();
