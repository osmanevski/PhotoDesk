'use strict';
/* PhotoDesk UI. Plain browser JavaScript, no build step.
 * Server state (`S`) is never edited in place: plan edits are made on a copy,
 * normalised to the server's invariants, then saved. Unsaved corner edits live
 * in `ui.draft` until the person saves or discards them. */

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const clone = v => structuredClone(v);
const LANG = window.APP_LANGUAGE === 'tr' ? 'tr' : 'en';
const STRINGS = JSON.parse($('#strings').textContent);

/* ---------- strings ---------- */
function t(key, vars = {}) {
  let s = STRINGS[key];
  if (s === undefined) { console.warn('Missing string', key); return key; }
  if (typeof s === 'object') s = (vars.n === 1 && s.one) ? s.one : s.other;
  return s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');
}

/* ---------- storage (never required) ---------- */
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

/* ---------- state ---------- */
let S = null;                    // last server state
const ui = {
  bid: store.get('fm-bid'), sid: null, rid: null, pid: null,
  view: 'scans', filter: 'all', zoom: false,
  draft: null,                   // unsaved plan {regions,pairs,notes} for ui.bid
  notes: {},                     // unsent AI instructions per batch
  uploading: null,               // {loaded,total}
  jobSeen: '', dismissed: '',
  confirmRemove: null,
  processOpen: null,             // null: open only while there is nothing to review
};

const batch = () => S?.batches.find(b => b.id === ui.bid) || null;
const plan = () => ui.draft || batch();
const scanOf = id => batch()?.scans.find(s => s.id === id);
const regionOf = id => plan()?.regions.find(r => r.id === id);
const pairOf = id => plan()?.pairs.find(p => p.id === id);
const running = () => S?.job.status === 'running';
const runningHere = () => running() && S.job.batch_id === ui.bid;
const backend = () => S?.settings.backend || 'local';
const approvedPairs = () => (batch()?.pairs || []).filter(p => !p.needs_review);

/* ---------- server ---------- */
async function api(path, data, method = 'POST') {
  const options = {method, headers: {'X-App-Token': window.APP_TOKEN}};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data); }
  const response = await fetch(path, options);
  let result = null;
  try { result = await response.json(); } catch { /* non-JSON error page */ }
  if (!response.ok) throw new Error(result?.error || t('error.http', {code: response.status}));
  return result;
}

function uploadRequest(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', path);
    xhr.setRequestHeader('X-App-Token', window.APP_TOKEN);
    xhr.upload.onprogress = e => e.lengthComputable && onProgress(e.loaded, e.total);
    xhr.upload.onload = () => onProgress(1, 1);
    xhr.onload = () => {
      let result = null;
      try { result = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(result);
      else reject(new Error(result?.error || (xhr.status === 413 ? t('error.tooLarge') : t('error.http', {code: xhr.status}))));
    };
    xhr.onerror = () => reject(new Error(t('error.network')));
    xhr.send(form);
  });
}

async function refresh() {
  S = await api('/api/state', undefined, 'GET');
  if (!batch()) { ui.bid = S.batches[0]?.id || null; ui.draft = null; }
  store.set('fm-bid', ui.bid || '');
  ui.jobSeen = jobKey(S.job);
  render();
}

function toast(message, kind = '') {
  const el = $('#toast');
  el.textContent = message; el.className = 'toast show ' + kind;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove('show'), kind === 'error' ? 9000 : 4500);
}

async function act(fn) {
  try { await fn(); }
  catch (e) { console.error(e); toast(e.message, 'error'); }
}

/* ---------- dialogs ---------- */
function ask(title, text, buttons) {
  // buttons: [{label, value, kind}] — resolves with value, or null when dismissed.
  const d = $('#confirmDialog');
  $('#confirmTitle').textContent = title;
  $('#confirmText').textContent = text;
  $('#confirmActions').innerHTML = buttons.map((b, i) => `<button class="btn ${b.kind || ''}" data-i="${i}">${esc(b.label)}</button>`).join('');
  return new Promise(resolve => {
    const done = v => { d.removeEventListener('close', onClose); d.close(); resolve(v); };
    const onClose = () => resolve(null);
    $('#confirmActions').onclick = e => { const b = e.target.closest('[data-i]'); if (b) done(buttons[b.dataset.i].value); };
    d.addEventListener('close', onClose, {once: true});
    d.showModal();
    $('#confirmActions .btn:last-child')?.focus();
  });
}

// Resolves pending corner edits before an action that reloads the plan.
async function settleDraft() {
  if (!ui.draft) return true;
  const choice = await ask(t('draft.title'), t('draft.text'), [
    {label: t('common.cancel'), value: 'cancel'},
    {label: t('draft.discard'), value: 'discard', kind: 'danger-text'},
    {label: t('draft.save'), value: 'save', kind: 'primary'},
  ]);
  if (choice === 'save') { await savePlan(ui.draft); return true; }
  if (choice === 'discard') { ui.draft = null; render(); return true; }
  return false;
}

document.addEventListener('click', e => {
  if (e.target.closest('[data-close]')) e.target.closest('dialog')?.close();
});

/* ---------- plan editing ---------- */
// Mirrors engine.validate_plan so a save is never rejected for a UI-made inconsistency.
function normalize(p) {
  const regions = new Map(p.regions.map(r => [r.id, r]));
  const b = batch();
  const group = r => b.scans.find(s => s.id === r.scan_id)?.group_key || '';
  const seenFront = new Set(), usedBacks = new Set();
  p.pairs = p.pairs.filter(pr => {
    const f = regions.get(pr.front_id);
    if (!f || f.role !== 'front' || seenFront.has(f.id)) return false;
    seenFront.add(f.id); return true;
  });
  for (const r of p.regions) {
    if (r.role === 'front' && !seenFront.has(r.id)) {
      p.pairs.push(newPair(r, t('notes.manualSide')));
    }
  }
  for (const pr of p.pairs) {
    if (pr.back_id) {
      const back = regions.get(pr.back_id), front = regions.get(pr.front_id);
      const crossGroup = back && group(back) && group(front) && group(back) !== group(front);
      if (!back || back.role !== 'back' || usedBacks.has(back.id) || crossGroup) {
        pr.back_id = null; pr.back_status = 'uncertain'; pr.needs_review = true;
      } else usedBacks.add(back.id);
    }
    if (pr.back_id && !['matched', 'uncertain'].includes(pr.back_status)) pr.back_id = null;
    if (!pr.back_id && pr.back_status === 'matched') pr.back_status = 'uncertain';
  }
  return p;
}

function newPair(region, note) {
  return {id: 'p-' + region.id, front_id: region.id, back_id: null, name: slugName(region.label || t('region.newName')),
    back_rotation_clockwise: 0, back_status: 'not_provided', confidence: 1, needs_review: true, matching_notes: note};
}

function slugName(s) {
  return String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'photo';
}

function workingPlan() {
  const b = batch();
  return ui.draft ? clone(ui.draft) : {regions: clone(b.regions), pairs: clone(b.pairs), notes: b.notes};
}

async function savePlan(p) {
  const b = batch();
  const bad = p.regions.find(r => !cornersValid(r.corners));
  if (bad) { ui.sid = bad.scan_id; ui.rid = bad.id; ui.view = 'scans'; render(); throw new Error(t('region.invalid')); }
  normalize(p);
  await api(`/api/batches/${ui.bid}/plan`, {revision: b.revision, regions: p.regions, pairs: p.pairs, notes: p.notes});
  ui.draft = null;
  await refresh();
}

// Apply fn to a copy of the plan; save now, or keep as an unsaved draft.
async function edit(fn, {save = true} = {}) {
  if (runningHere()) throw new Error(t('job.busyEdit'));
  const p = workingPlan();
  fn(p);
  if (save) await savePlan(p);
  else { ui.draft = normalize(p); render(); }
}

function cornersValid(c) {
  // Convex, clockwise, non-degenerate: same rule as imaging.validate_corners.
  let sign = 0, area = 0;
  for (let i = 0; i < 4; i++) {
    const [ax, ay] = c[i], [bx, by] = c[(i + 1) % 4], [cx, cy] = c[(i + 2) % 4];
    const cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx);
    if (cross === 0) return false;
    if (sign && Math.sign(cross) !== sign) return false;
    sign = Math.sign(cross);
    area += ax * by - bx * ay;
  }
  return Math.abs(area / 2) * 1e8 >= 10000 && area > 0;
}

/* ---------- small helpers ---------- */
const hash = s => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(36); };
// Keyed by the saved geometry the server renders, never by an unsaved draft.
function previewURL(p) {
  const pl = batch(), ids = [p.front_id, p.back_id].filter(Boolean);
  const key = JSON.stringify([p.back_id, p.back_rotation_clockwise, ids.map(id => { const r = pl.regions.find(x => x.id === id); return r && [r.corners, r.rotation_clockwise, r.scan_id]; })]);
  return `/api/batches/${ui.bid}/pair/${encodeURIComponent(p.id)}/preview?v=${hash(key)}`;
}
const scanURL = s => `/api/batches/${ui.bid}/scan/${s.id}?v=1`;
const num = i => String(i + 1).padStart(3, '0');
const statusLabel = p => ({matched: t('back.matched'), blank: t('back.blank'), not_provided: t('back.none'), uncertain: t('back.uncertain')}[p.back_status]);
const roleLabel = r => ({front: t('role.front'), back: t('role.back'), blank: t('role.blank')}[r]);
const regionName = r => {
  const s = scanOf(r.scan_id); const i = plan().regions.filter(x => x.scan_id === r.scan_id).indexOf(r);
  return `${s ? s.name : ''} · ${i + 1}`;
};
const opt = (value, label, selected, extra = '') => `<option value="${esc(value)}" ${selected ? 'selected' : ''} ${extra}>${esc(label)}</option>`;

/* ---------- render ---------- */
function render() {
  if (!S) return;
  renderTop();
  renderJob();
  const b = batch();
  const app = $('#app');
  if (!b) { app.className = 'app'; app.innerHTML = welcomeView(); return; }
  if (!b.scans.some(s => s.id === ui.sid)) ui.sid = b.scans[0]?.id || null;
  const pl = plan();
  if (!pl.pairs.some(p => p.id === ui.pid)) ui.pid = pl.pairs[0]?.id || null;
  if (!pl.regions.some(r => r.id === ui.rid && r.scan_id === ui.sid)) ui.rid = pl.regions.find(r => r.scan_id === ui.sid)?.id || null;
  if (!b.scans.length) ui.view = 'scans';
  app.className = 'app workspace';
  app.innerHTML = `<aside class="sidebar">${sidebar()}</aside>
    <section class="main">${heading()}${b.scans.length ? (ui.view === 'photos' ? photosView() : scanView()) : dropView()}</section>
    <aside class="inspector">${inspector()}</aside>`;
  bindStage();
}

function renderTop() {
  const b = batch();
  $('#batchSwitch').innerHTML = S.batches.length ? `<select id="batchSelect" aria-label="${esc(t('batch.switch'))}">${S.batches.map(x => opt(x.id, x.name, x.id === ui.bid)).join('')}</select><button class="btn quiet" id="newBatch">${esc(t('batch.new'))}</button>` : '';
  const c = S.settings, router = c.backend === 'openrouter';
  const name = c.backend === 'local' ? t('mode.localShort') : (router ? 'OpenRouter · ' + (c.api_model || t('settings.noModel')) : (S.models.find(m => m.id === c.model)?.name || c.model) + ' · ' + c.effort);
  $('#modelState').innerHTML = `<span class="dot ${c.backend === 'local' ? '' : 'ai'}"></span>${esc(name)}`;
  const ready = approvedPairs().length;
  const btn = $('#exportTop');
  btn.disabled = !b || !ready || runningHere() || !!ui.draft;
  btn.innerHTML = ready ? `${esc(t('export.open'))} <span class="count">${ready}</span>` : esc(t('export.open'));
  btn.title = !ready ? t('export.none') : ui.draft ? t('draft.text') : '';
}

const jobKey = j => JSON.stringify([j.status, j.batch_id, j.message, j.started]);

function renderJob() {
  const bar = $('#jobbar'), j = S.job;
  if (ui.uploading) {
    const {loaded, total} = ui.uploading, pct = total ? Math.round(loaded / total * 100) : 0;
    bar.hidden = false; bar.className = 'jobbar';
    $('#jobtext').textContent = pct >= 100 ? t('upload.processing') : t('upload.progress', {pct});
    $('#jobprogress').hidden = false; $('#jobprogress i').style.width = pct + '%';
    $('#cancelJob').hidden = true; $('#dismissJob').hidden = true; bar.querySelector('.spinner').hidden = false;
    return;
  }
  $('#jobprogress').hidden = true;
  const visible = ['running', 'error', 'done', 'cancelled'].includes(j.status) && ui.dismissed !== jobKey(j);
  bar.hidden = !visible;
  bar.className = 'jobbar ' + (j.status === 'error' ? 'error' : j.status === 'done' ? 'done' : '');
  $('#jobtext').textContent = j.message;
  $('#cancelJob').hidden = j.status !== 'running';
  $('#dismissJob').hidden = j.status === 'running';
  bar.querySelector('.spinner').hidden = j.status !== 'running';
}

function welcomeView() {
  return `<div class="welcome">
    <div class="welcome-art" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
    <h1>${esc(t('welcome.title'))}</h1>
    <p>${esc(t('welcome.text'))}</p>
    <div class="drop big" data-action="upload" role="button" tabindex="0"><b>${esc(t('drop.title'))}</b><span>${esc(t('drop.formats'))}</span></div>
    <ol class="flow"><li>${esc(t('flow.add'))}</li><li>${esc(t('flow.review'))}</li><li>${esc(t('flow.save'))}</li></ol>
    <p class="help">${esc(t('welcome.naming'))}</p>
  </div>`;
}

function sidebar() {
  const b = batch(), pl = plan();
  const scans = b.scans.map(s => {
    const n = pl.regions.filter(r => r.scan_id === s.id).length;
    return `<li class="scan ${s.id === ui.sid && ui.view === 'scans' ? 'active' : ''}" data-scan="${esc(s.id)}">
      <button class="scan-open" aria-label="${esc(s.name)}"><img src="${scanURL(s)}" alt="" loading="lazy"></button>
      <div class="scan-info">
        <div class="scan-name" title="${esc(s.name)}">${esc(s.name)}</div>
        <div class="meta">${s.page > 1 ? esc(t('scan.page', {n: s.page})) + ' · ' : ''}${n ? esc(t('scan.regions', {n})) : esc(t('scan.unprocessed'))}</div>
        <select data-role-hint="${esc(s.id)}" aria-label="${esc(t('scan.hintLabel', {name: s.name}))}" ${runningHere() ? 'disabled' : ''}>
          ${[['auto', t('hint.auto')], ['front', t('hint.front')], ['back', t('hint.back')]].map(([v, l]) => opt(v, l, s.role_hint === v)).join('')}
        </select>
      </div>
      ${n ? '' : `<button class="icon-btn remove-scan" data-remove-scan="${esc(s.id)}" title="${esc(t('scan.remove'))}" aria-label="${esc(t('scan.remove'))}">×</button>`}
    </li>`;
  }).join('');
  return `<div class="side-head"><h2>${esc(t('scans.title'))}</h2><span class="count">${b.scans.length}</span></div>
    <div class="drop small" data-action="upload" role="button" tabindex="0"><b>${esc(t('drop.add'))}</b><span>${esc(t('drop.orDrag'))}</span></div>
    <ul class="scan-list">${scans}</ul>
    <p class="side-foot">${esc(t('side.foot'))}</p>`;
}

function heading() {
  const b = batch(), pairs = b.pairs, ok = approvedPairs().length;
  const summary = pairs.length ? t('summary.pairs', {n: pairs.length, ok, review: pairs.length - ok}) : b.scans.length ? t('summary.scansOnly', {n: b.scans.length}) : t('summary.empty');
  const tabs = b.scans.length ? `<nav class="tabs" role="tablist">
      <button role="tab" data-view="scans" aria-selected="${ui.view === 'scans'}">${esc(t('tab.scans'))}</button>
      <button role="tab" data-view="photos" aria-selected="${ui.view === 'photos'}">${esc(t('tab.photos'))} <span class="count">${pairs.length}</span></button>
    </nav>` : '';
  const undo = b.undo_available ? `<button class="btn small" data-action="undo" ${runningHere() ? 'disabled' : ''}>↶ ${esc(t('undo'))}</button>` : '';
  return `<header class="main-head"><div><h1>${esc(b.name)}</h1><p>${esc(summary)}</p></div>${undo}</header>${tabs}`;
}

function dropView() {
  return `<div class="drop big" data-action="upload" role="button" tabindex="0"><b>${esc(t('drop.title'))}</b><span>${esc(t('drop.formats'))}</span></div>
    <div class="guide">
      <h3>${esc(t('guide.title'))}</h3>
      <p>${esc(t('welcome.naming'))}</p>
      <p>${esc(t('guide.position'))}</p>
    </div>`;
}

/* ---------- scan editor ---------- */
function scanView() {
  const s = scanOf(ui.sid); if (!s) return '';
  const regs = plan().regions.filter(r => r.scan_id === s.id);
  const locked = runningHere();
  return `<div class="stage-tools">
      <button class="btn small" data-action="add-region" ${locked ? 'disabled' : ''}>＋ ${esc(t('region.add'))}</button>
      <button class="btn small" data-action="zoom" aria-pressed="${ui.zoom}">${esc(ui.zoom ? t('zoom.fit') : t('zoom.in'))}</button>
      ${ui.draft ? `<div class="draft-bar" role="status"><span>● ${esc(t('draft.bar'))}</span><button class="btn small" data-action="discard-draft">${esc(t('draft.discard'))}</button><button class="btn small primary" data-action="save-draft">${esc(t('draft.save'))}</button></div>`
        : `<span class="hint">${esc(regs.length ? t('stage.hint') : t('stage.hintEmpty'))}</span>`}
    </div>
    <div class="table ${ui.zoom ? 'zoomed' : ''}" id="stageScroll">
      <div class="stage" style="aspect-ratio:${s.width}/${s.height};--r:${(s.width / s.height).toFixed(4)}">
        <img src="${scanURL(s)}" alt="${esc(t('stage.alt', {name: s.name}))}" draggable="false">
        <svg id="stageSvg" viewBox="0 0 ${s.width} ${s.height}" preserveAspectRatio="none" aria-label="${esc(t('stage.label'))}"></svg>
      </div>
    </div>`;
}

function drawStage() {
  const svg = $('#stageSvg'); if (!svg) return;
  const s = scanOf(ui.sid), W = s.width, H = s.height;
  const k = W / (svg.getBoundingClientRect().width || W);   // viewBox units per screen px
  const regs = plan().regions.filter(r => r.scan_id === s.id);
  svg.innerHTML = regs.map((r, i) => {
    const pts = r.corners.map(([x, y]) => [x * W, y * H]);
    const active = r.id === ui.rid;
    const bad = active && !cornersValid(r.corners);
    const [lx, ly] = pts[0];
    let marks = '';
    if (active) {
      marks = pts.map((p, j) => {
        const prev = pts[(j + 3) % 4], next = pts[(j + 1) % 4], L = 22 * k;
        const leg = q => { const dx = q[0] - p[0], dy = q[1] - p[1], d = Math.hypot(dx, dy) || 1; return [p[0] + dx / d * L, p[1] + dy / d * L]; };
        const a = leg(prev), c = leg(next);
        return `<g class="corner" data-corner="${j}"><circle cx="${p[0]}" cy="${p[1]}" r="${18 * k}"></circle><path d="M${a[0]},${a[1]} L${p[0]},${p[1]} L${c[0]},${c[1]}"></path></g>`;
      }).join('');
    }
    return `<g class="region ${active ? 'active' : ''} ${bad ? 'bad' : ''} role-${r.role}" data-region="${esc(r.id)}">
      <polygon points="${pts.map(p => p.join(',')).join(' ')}"></polygon>
      <text x="${lx + 16 * k}" y="${ly + 34 * k}" font-size="${16 * k}">${i + 1}</text>${marks}</g>`;
  }).join('');
}

let drag = null;
const stageObserver = new ResizeObserver(() => drawStage());
// The table fills the rest of the window so a whole scan is visible without scrolling.
function fitStage() {
  const table = $('#stageScroll'); if (!table) return;
  table.style.setProperty('--h', Math.max(320, innerHeight - table.getBoundingClientRect().top - 24) + 'px');
}
addEventListener('resize', fitStage);

function bindStage() {
  const svg = $('#stageSvg');
  stageObserver.disconnect();
  if (!svg) return;
  fitStage();
  drawStage();
  stageObserver.observe(svg);
  const point = e => { const r = svg.getBoundingClientRect(); return [Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))]; };
  svg.addEventListener('pointerdown', e => {
    if (runningHere() || e.button !== 0) return;
    const corner = e.target.closest('[data-corner]'), reg = e.target.closest('[data-region]');
    if (!reg) return;
    if (reg.dataset.region !== ui.rid) { ui.rid = reg.dataset.region; ui.confirmRemove = null; render(); return; }
    const hadDraft = !!ui.draft;
    if (!hadDraft) ui.draft = workingPlan();
    const r = ui.draft.regions.find(x => x.id === ui.rid);
    drag = {corner: corner ? Number(corner.dataset.corner) : null, start: point(e), orig: clone(r.corners), moved: false, hadDraft};
    svg.setPointerCapture(e.pointerId); e.preventDefault();
  });
  svg.addEventListener('pointermove', e => {
    if (!drag) return;
    const r = ui.draft.regions.find(x => x.id === ui.rid), [x, y] = point(e);
    if (drag.corner !== null) r.corners[drag.corner] = [x, y];
    else {
      // Move the whole boundary, clamped so no corner leaves the scan.
      let dx = x - drag.start[0], dy = y - drag.start[1];
      for (const [cx, cy] of drag.orig) { dx = Math.max(-cx, Math.min(1 - cx, dx)); dy = Math.max(-cy, Math.min(1 - cy, dy)); }
      r.corners = drag.orig.map(([cx, cy]) => [cx + dx, cy + dy]);
    }
    drag.moved = true; drawStage();
  });
  const end = () => {
    if (!drag) return;
    const {moved, hadDraft} = drag; drag = null;
    if (moved) { markNeedsReview(ui.draft, ui.rid); render(); }
    else if (!hadDraft) ui.draft = null;
  };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
}

function markNeedsReview(p, rid) {
  for (const pr of p.pairs) if (pr.front_id === rid || pr.back_id === rid) pr.needs_review = true;
}

/* ---------- photos ---------- */
function photosView() {
  const pairs = batch().pairs;
  if (!pairs.length) return `<div class="empty-note"><p>${esc(t('photos.empty'))}</p></div>`;
  const review = pairs.filter(p => p.needs_review).length;
  const list = pairs.map((p, i) => ({p, i})).filter(({p}) => ui.filter === 'all' || (ui.filter === 'review') === p.needs_review);
  const chips = [['all', t('filter.all'), pairs.length], ['review', t('filter.review'), review], ['approved', t('filter.approved'), pairs.length - review]]
    .map(([v, l, n]) => `<button class="chip-btn" data-filter="${v}" aria-pressed="${ui.filter === v}">${esc(l)} <span>${n}</span></button>`).join('');
  const cards = list.map(({p, i}) => `<button class="card ${p.id === ui.pid ? 'active' : ''}" data-pair="${esc(p.id)}">
      <span class="card-photo"><img src="${previewURL(p)}" alt="" loading="lazy" decoding="async"></span>
      <span class="card-info"><span class="num">${num(i)}</span><span class="card-name">${esc(p.name)}</span>
      <span class="tags"><span class="tag ${p.needs_review ? 'warn' : 'ok'}">${esc(p.needs_review ? t('status.review') : t('status.approved'))}</span><span class="tag">${esc(statusLabel(p))}</span></span></span>
    </button>`).join('');
  return `<div class="filters" role="group" aria-label="${esc(t('filter.label'))}">${chips}</div>
    ${list.length ? `<div class="grid">${cards}</div>` : `<p class="empty-note">${esc(t('filter.nothing'))}</p>`}
    ${batch().notes ? `<details class="notes"><summary>${esc(t('photos.notes'))}</summary><p>${esc(batch().notes)}</p></details>` : ''}
    <p class="help layout-note">${esc(t('photos.layoutNote'))}</p>`;
}

/* ---------- inspector ---------- */
function inspector() {
  const b = batch();
  if (!b.scans.length) return `<div class="insp-intro"><h2>${esc(t('intro.title'))}</h2><p class="help">${esc(t('intro.text'))}</p></div>`;
  const body = ui.view === 'photos' && b.pairs.some(p => p.id === ui.pid) ? pairPanel() : regionPanel();
  return body + processPanel();
}

function pairPanel() {
  const b = batch(), p = b.pairs.find(x => x.id === ui.pid), i = b.pairs.indexOf(p);
  const front = b.regions.find(r => r.id === p.front_id), frontScan = scanOf(front.scan_id);
  const locked = runningHere() ? 'disabled' : '';
  const owner = new Map(b.pairs.filter(x => x.back_id && x.id !== p.id).map(x => [x.back_id, x]));
  const backs = b.regions.filter(r => r.role === 'back' && !(frontScan.group_key && scanOf(r.scan_id)?.group_key && scanOf(r.scan_id).group_key !== frontScan.group_key));
  const backOptions = opt('', t('back.select'), !p.back_id) + backs.map(r => {
    const other = owner.get(r.id);
    return opt(r.id, regionName(r) + (other ? ' — ' + t('back.usedBy', {n: num(b.pairs.indexOf(other))}) : ''), r.id === p.back_id);
  }).join('');
  const statuses = [['matched', t('back.matched')], ['blank', t('back.blank')], ['not_provided', t('back.none')], ['uncertain', t('back.uncertain')]]
    .map(([v, l]) => opt(v, l, p.back_status === v, v === 'matched' && !p.back_id ? 'disabled' : '')).join('');
  return `<div class="insp-head"><span class="num">${esc(t('photo.number', {n: num(i)}))}</span>
      <span class="tag ${p.needs_review ? 'warn' : 'ok'}">${esc(p.needs_review ? t('status.review') : t('status.approved'))}</span></div>
    <a class="insp-preview" href="${previewURL(p)}" target="_blank" rel="noopener" title="${esc(t('photo.openLarge'))}"><img src="${previewURL(p)}" alt="${esc(p.name)}"></a>
    <label class="field">${esc(t('photo.name'))}<input id="pairName" value="${esc(p.name)}" maxlength="100" ${locked}></label>
    <label class="field">${esc(t('photo.back'))}<select id="pairBack" ${locked}>${backOptions}</select></label>
    <label class="field">${esc(t('photo.backStatus'))}<select id="backStatus" ${locked}>${statuses}</select></label>
    <div class="rot-row"><span>${esc(t('photo.frontRotation'))}</span><code>${front.rotation_clockwise}°</code><button class="btn small" data-action="rotate-front" ${locked} title="R">↻ 90°</button></div>
    ${p.back_id ? `<div class="rot-row"><span>${esc(t('photo.backRotation'))}</span><code>${p.back_rotation_clockwise}°</code><button class="btn small" data-action="rotate-back" ${locked}>↻ 180°</button></div>` : ''}
    ${p.matching_notes ? `<p class="note">${esc(p.matching_notes)}</p>` : ''}
    <div class="actions">
      ${p.needs_review
        ? `<button class="btn primary" data-action="approve" ${locked} title="A">✓ ${esc(t('photo.approveNext'))}</button>`
        : `<button class="btn" data-action="unapprove" ${locked}>${esc(t('photo.unapprove'))}</button>`}
    </div>
    <div class="links"><button class="link" data-action="edit-front">${esc(t('photo.editFront'))}</button>${p.back_id ? `<button class="link" data-action="edit-back">${esc(t('photo.editBack'))}</button>` : ''}</div>
    <p class="keys">${t('photo.keys')}</p>`;
}

function regionPanel() {
  const pl = plan(), s = scanOf(ui.sid), regs = pl.regions.filter(r => r.scan_id === ui.sid), r = regionOf(ui.rid);
  const locked = runningHere() ? 'disabled' : '';
  if (!regs.length) return `<h2 class="insp-title">${esc(t('region.noneTitle'))}</h2><p class="help">${esc(t('region.noneText'))}</p>`;
  const list = regs.map((x, i) => `<li><button class="region-item ${x.id === ui.rid ? 'active' : ''}" data-region-pick="${esc(x.id)}"><span class="num">${i + 1}</span>${esc(roleLabel(x.role))}${cornersValid(x.corners) ? '' : ' <span class="tag bad">!</span>'}</button></li>`).join('');
  const pair = r && pl.pairs.find(p => p.front_id === r.id || p.back_id === r.id);
  const removing = ui.confirmRemove === r?.id;
  return `<h2 class="insp-title">${esc(t('region.title', {name: s.name}))}</h2>
    <ul class="region-list">${list}</ul>
    ${r ? `<div class="region-edit">
      <label class="field">${esc(t('region.role'))}<select id="regionRole" ${locked}>${['front', 'back', 'blank'].map(v => opt(v, roleLabel(v), r.role === v)).join('')}</select></label>
      <div class="rot-row"><span>${esc(t('region.rotation'))}</span><code>${r.rotation_clockwise}°</code><button class="btn small" data-action="rotate-region" ${locked}>↻ 90°</button></div>
      ${cornersValid(r.corners) ? '' : `<p class="warn-text">${esc(t('region.invalid'))}</p>`}
      ${ui.draft ? `<button class="btn primary full" data-action="save-draft">${esc(t('draft.save'))}</button>` : ''}
      ${pair ? `<button class="link" data-goto-pair="${esc(pair.id)}">${esc(t('region.openPhoto', {n: num(pl.pairs.indexOf(pair))}))}</button>` : ''}
      <button class="btn small danger-text full" data-action="remove-region" ${locked}>${esc(removing ? t('region.removeConfirm') : t('region.remove'))}</button>
    </div>` : ''}`;
}

function processPanel() {
  const b = batch(), c = S.settings, mode = c.backend, router = mode === 'openrouter';
  const locked = running() ? 'disabled' : '';
  const models = router ? S.openrouter.models : S.models;
  const mkey = router ? 'api_model' : 'model', ekey = router ? 'api_effort' : 'effort';
  const model = models.find(m => m.id === c[mkey]);
  const efforts = model ? model.efforts : [router ? 'default' : 'medium'];
  const pending = b.scans.filter(s => !b.regions.some(r => r.scan_id === s.id)).length;
  const hasPlan = b.pairs.length > 0;
  const blocked = runningHere() || !!ui.draft || !b.scans.length ? 'disabled' : '';
  let fields = `<label class="field">${esc(t('settings.method'))}<select id="backendSelect" ${locked}>
      ${opt('local', t('mode.local'), mode === 'local')}${opt('ai', t('mode.codex'), mode === 'ai')}${opt('openrouter', t('mode.openrouter'), router)}</select></label>`;
  if (mode === 'local') {
    fields += `<label class="field">${esc(t('settings.layout'))}<select id="layoutSelect" ${locked}>${Object.entries(S.layouts).map(([v, l]) => opt(v, l, v === c.layout)).join('')}</select></label>
      <p class="help">${esc(t('settings.localHelp'))}</p>`;
  } else {
    fields += `<div class="field-row"><label class="field">${esc(t('settings.model'))}<select id="modelSelect" ${locked}>${router ? opt('', t('settings.noModel'), !c.api_model) : ''}${models.map(m => opt(m.id, m.name, m.id === c[mkey])).join('')}</select></label>
      <label class="field narrow">${esc(t('settings.effort'))}<select id="effortSelect" ${locked}>${efforts.map(e => opt(e, e === 'default' ? t('settings.effortDefault') : e, e === c[ekey])).join('')}</select></label></div>`;
    if (router) fields += `<div class="btn-row"><button class="btn small" data-action="api-key" ${locked}>${esc(S.api_key_saved ? '✓ ' + t('api.connected') : t('api.add'))}</button><button class="btn small" data-action="refresh-models" ${locked}>${esc(t('api.refreshModels'))}</button></div>`;
    fields += `<label class="field">${esc(t('ai.note'))}<textarea id="instruction" rows="3" placeholder="${esc(t('ai.placeholder'))}">${esc(ui.notes[ui.bid] ?? b.instruction)}</textarea></label>
      <p class="help">${esc(router ? t('settings.routerHelp') : t('settings.codexHelp'))}</p>`;
  }
  const canRevise = mode !== 'local' && hasPlan && !pending;
  const label = runningHere() ? t('process.running') : canRevise ? t('process.revise') : hasPlan ? t('process.rerun') : t('process.run');
  const main = `<button class="btn primary full" data-action="${canRevise ? 'revise' : 'analyze'}" ${blocked}>${esc(label)}</button>`;
  const second = canRevise ? `<button class="btn small full" data-action="analyze" ${blocked}>${esc(t('process.rerunAll'))}</button>` : '';
  const pendingNote = pending && hasPlan ? `<p class="help">${esc(t('process.pending', {n: pending}))}</p>` : '';
  const open = ui.processOpen ?? !(hasPlan && !pending);
  return `<details class="process" ${open ? 'open' : ''}><summary>${esc(t('process.title'))}</summary>${fields}${pendingNote}${main}${second}</details>`;
}

/* ---------- actions ---------- */
const actions = {
  async upload() {
    if (runningHere() || ui.uploading) return toast(t('job.wait'));
    $('#fileInput').click();
  },
  async zoom() { ui.zoom = !ui.zoom; render(); },
  async undo() {
    if (!await settleDraft()) return;
    await api(`/api/batches/${ui.bid}/undo`, {}); await refresh(); toast(t('undo.done'));
  },
  async analyze() { await process('analyze'); },
  async revise() { await process('revise'); },
  async 'save-draft'() {
    await savePlan(ui.draft); toast(t('draft.saved'));
  },
  async 'discard-draft'() { ui.draft = null; render(); },
  async 'add-region'() {
    const s = scanOf(ui.sid), id = `${s.id}-m-${Date.now().toString(36)}`;
    const count = plan().regions.filter(r => r.scan_id === s.id).length;
    const role = s.role_hint === 'back' ? 'back' : 'front';
    await edit(p => {
      p.regions.push({id, scan_id: s.id, role, label: `${s.name} · ${count + 1}`, corners: [[.3, .3], [.7, .3], [.7, .7], [.3, .7]], rotation_clockwise: 0, confidence: 1});
      if (role === 'front') p.pairs.push(newPair({id, label: t('region.newName')}, t('notes.manual')));
    }, {save: false});
    ui.rid = id; render(); toast(t('region.added'));
  },
  async 'rotate-region'() {
    await edit(p => { const r = p.regions.find(x => x.id === ui.rid); r.rotation_clockwise = (r.rotation_clockwise + 90) % 360; markNeedsReview(p, r.id); }, {save: !ui.draft});
  },
  async 'remove-region'() {
    if (ui.confirmRemove !== ui.rid) { ui.confirmRemove = ui.rid; render(); return; }
    const id = ui.rid; ui.confirmRemove = null;
    await edit(p => {
      p.regions = p.regions.filter(r => r.id !== id);
      for (const pr of p.pairs) if (pr.back_id === id) { pr.back_id = null; pr.back_status = 'uncertain'; pr.needs_review = true; }
    }, {save: !ui.draft});
  },
  async 'rotate-front'() {
    const pid = ui.pid;
    await edit(p => { const pr = p.pairs.find(x => x.id === pid), r = p.regions.find(x => x.id === pr.front_id); r.rotation_clockwise = (r.rotation_clockwise + 90) % 360; pr.needs_review = true; });
  },
  async 'rotate-back'() {
    const pid = ui.pid;
    await edit(p => { const pr = p.pairs.find(x => x.id === pid); pr.back_rotation_clockwise = (pr.back_rotation_clockwise + 180) % 360; pr.needs_review = true; });
  },
  async approve() {
    const pr = pairOf(ui.pid);
    if (pr.back_status === 'uncertain') throw new Error(t('photo.uncertain'));
    const pid = pr.id;
    await edit(p => { p.pairs.find(x => x.id === pid).needs_review = false; });
    // Continue with the next photo still waiting for review.
    const pairs = batch().pairs, start = pairs.findIndex(x => x.id === pid);
    const next = [...pairs.slice(start + 1), ...pairs.slice(0, start)].find(x => x.needs_review);
    if (next) { ui.pid = next.id; render(); scrollToActive(); }
    else toast(pairs.every(x => !x.needs_review) ? t('photo.allApproved') : t('photo.approved'));
  },
  async unapprove() {
    const pid = ui.pid;
    await edit(p => { p.pairs.find(x => x.id === pid).needs_review = true; });
  },
  async 'edit-front'() { focusRegion(regionOf(pairOf(ui.pid).front_id)); },
  async 'edit-back'() { focusRegion(regionOf(pairOf(ui.pid).back_id)); },
  async 'api-key'() {
    $('#apiKey').value = '';
    $('#apiStatus').textContent = S.api_key_saved ? t('api.savedHidden') : t('api.notSaved');
    $('#apiDialog').showModal();
  },
  async 'refresh-models'(btn) {
    btn.disabled = true; btn.textContent = t('common.loading');
    try { S.openrouter = await api('/api/openrouter/models', {}); toast(t('api.modelsFound', {n: S.openrouter.models.length})); }
    finally { render(); }
  },
};

function focusRegion(r) {
  if (!r) return;
  ui.sid = r.scan_id; ui.rid = r.id; ui.view = 'scans'; render();
}

function scrollToActive() { $('.card.active')?.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }

async function process(mode) {
  if (!await settleDraft()) return;
  const b = batch();
  if (mode === 'analyze' && b.pairs.length) {
    const ok = await ask(t('process.confirmTitle'), t('process.confirmText'), [{label: t('common.cancel'), value: false}, {label: t('process.rerun'), value: true, kind: 'primary'}]);
    if (!ok) return;
  }
  const instruction = $('#instruction')?.value ?? ui.notes[ui.bid] ?? b.instruction ?? '';
  await api(`/api/batches/${ui.bid}/analyze`, {instruction, mode});
  ui.dismissed = '';
  await refresh();
  poll.soon();
}

/* ---------- events ---------- */
$('#app').addEventListener('click', e => act(async () => {
  const a = e.target.closest('[data-action]');
  if (a && !a.disabled) {
    if (a.dataset.action !== 'remove-region') ui.confirmRemove = null;
    return actions[a.dataset.action](a);
  }
  const rm = e.target.closest('[data-remove-scan]');
  if (rm) {
    const s = scanOf(rm.dataset.removeScan);
    const ok = await ask(t('scan.removeTitle'), t('scan.removeText', {name: s.name}), [{label: t('common.cancel'), value: false}, {label: t('scan.remove'), value: true, kind: 'danger'}]);
    if (ok) { await api(`/api/batches/${ui.bid}/remove-scan/${s.id}`, {}); await refresh(); }
    return;
  }
  const scan = e.target.closest('[data-scan]');
  if (scan && !e.target.closest('select')) {
    ui.sid = scan.dataset.scan; ui.rid = null; ui.view = 'scans'; ui.confirmRemove = null; render(); return;
  }
  const view = e.target.closest('[data-view]');
  if (view) {
    if (view.dataset.view === 'photos' && !await settleDraft()) return;
    ui.view = view.dataset.view; render(); return;
  }
  const filter = e.target.closest('[data-filter]');
  if (filter) { ui.filter = filter.dataset.filter; render(); return; }
  const card = e.target.closest('[data-pair]');
  if (card) { ui.pid = card.dataset.pair; render(); return; }
  const pick = e.target.closest('[data-region-pick]');
  if (pick) { ui.rid = pick.dataset.regionPick; ui.confirmRemove = null; render(); return; }
  const go = e.target.closest('[data-goto-pair]');
  if (go && await settleDraft()) { ui.pid = go.dataset.gotoPair; ui.view = 'photos'; ui.filter = 'all'; render(); scrollToActive(); }
}));

$('#app').addEventListener('keydown', e => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[role="button"]')) { e.preventDefault(); e.target.click(); }
  if (e.key === 'Enter' && e.target.id === 'pairName') e.target.blur();
});

$('#app').addEventListener('toggle', e => { if (e.target.matches?.('.process')) ui.processOpen = e.target.open; }, true);

$('#app').addEventListener('input', e => {
  if (e.target.id === 'instruction') ui.notes[ui.bid] = e.target.value;
});

$('#app').addEventListener('change', e => act(async () => {
  const el = e.target, pid = ui.pid;
  if (el.dataset.roleHint) {
    await api(`/api/batches/${ui.bid}/scan/${el.dataset.roleHint}`, {role_hint: el.value, revision: batch().revision});
    return refresh();
  }
  if (el.id === 'pairName') {
    const name = el.value.trim() || 'photo';
    if (name === pairOf(pid).name) return;
    return edit(p => { p.pairs.find(x => x.id === pid).name = name; });
  }
  if (el.id === 'pairBack') {
    const back = el.value || null;
    return edit(p => {
      const pr = p.pairs.find(x => x.id === pid);
      for (const other of p.pairs) if (back && other !== pr && other.back_id === back) { other.back_id = null; other.back_status = 'uncertain'; other.needs_review = true; }
      pr.back_id = back; pr.back_status = back ? 'matched' : 'uncertain'; pr.needs_review = true;
    });
  }
  if (el.id === 'backStatus') {
    return edit(p => {
      const pr = p.pairs.find(x => x.id === pid);
      pr.back_status = el.value; if (['blank', 'not_provided'].includes(el.value)) pr.back_id = null; pr.needs_review = true;
    });
  }
  if (el.id === 'regionRole') {
    const rid = ui.rid;
    return edit(p => {
      const r = p.regions.find(x => x.id === rid); r.role = el.value;
      p.pairs = p.pairs.filter(pr => !(pr.front_id === rid && el.value !== 'front'));
      markNeedsReview(p, rid);
    }, {save: !ui.draft});
  }
  if (['backendSelect', 'modelSelect', 'effortSelect', 'layoutSelect'].includes(el.id)) return changeSettings(el);
}));

async function changeSettings(el) {
  const c = {...S.settings}, router = c.backend === 'openrouter';
  const models = router ? S.openrouter.models : S.models, mkey = router ? 'api_model' : 'model', ekey = router ? 'api_effort' : 'effort';
  if (el.id === 'backendSelect') c.backend = el.value;
  if (el.id === 'modelSelect') {
    c[mkey] = el.value;
    const m = models.find(x => x.id === el.value);
    if (m && !m.efforts.includes(c[ekey])) c[ekey] = router ? (m.efforts.includes('default') ? 'default' : m.efforts[0]) : (m.efforts.includes('medium') ? 'medium' : m.efforts[0]);
  }
  if (el.id === 'effortSelect') c[ekey] = el.value;
  if (el.id === 'layoutSelect') c.layout = el.value;
  try { S.settings = await api('/api/settings', c); }
  finally { render(); }
}

/* topbar */
$('#batchSwitch').addEventListener('change', e => act(async () => {
  if (e.target.id !== 'batchSelect') return;
  const next = e.target.value;
  if (!await settleDraft()) { e.target.value = ui.bid; return; }
  ui.bid = next; ui.sid = ui.pid = ui.rid = null; ui.view = 'scans'; ui.draft = null;
  await refresh();
  if (batch()?.pairs.length) { ui.view = 'photos'; render(); }
}));
$('#batchSwitch').addEventListener('click', e => { if (e.target.id === 'newBatch') openNewBatch(); });

function openNewBatch() { $('#batchName').value = ''; $('#newDialog').showModal(); $('#batchName').focus(); }

$('#newForm').addEventListener('submit', e => { e.preventDefault(); act(async () => {
  if (!await settleDraft()) return;
  const b = await api('/api/batches', {name: $('#batchName').value.trim()});
  $('#newDialog').close();
  ui.bid = b.id; ui.sid = ui.pid = ui.rid = null; ui.view = 'scans'; ui.draft = null;
  await refresh();
}); });

/* theme: follows the system unless the person picks light or dark */
const THEMES = ['auto', 'light', 'dark'];
const THEME_ICONS = {
  auto: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor"/></svg>',
  light: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6 13 13M3 13l1.4-1.4M11.6 4.4 13 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  dark: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13.5 10.2A6 6 0 0 1 5.8 2.5a6 6 0 1 0 7.7 7.7z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
};
function applyTheme(theme) {
  if (theme === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  const btn = $('#themeToggle'), label = {auto: t('theme.auto'), light: t('theme.light'), dark: t('theme.dark')}[theme];
  btn.innerHTML = THEME_ICONS[theme];
  btn.title = label; btn.setAttribute('aria-label', label);
}
applyTheme(THEMES.includes(store.get('fm-theme')) ? store.get('fm-theme') : 'auto');
$('#themeToggle').addEventListener('click', () => {
  const current = document.documentElement.dataset.theme || 'auto';
  const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
  store.set('fm-theme', next); applyTheme(next);
});

$('#languageSelect').value = LANG;
$('#languageSelect').addEventListener('change', e => act(async () => {
  if (!await settleDraft()) { e.target.value = LANG; return; }
  document.cookie = `photo-desk-language=${e.target.value}; Path=/; SameSite=Strict; Max-Age=31536000`;
  location.reload();
}));

/* job bar */
$('#cancelJob').addEventListener('click', () => act(async () => { await api('/api/cancel', {}); $('#jobtext').textContent = t('job.cancelling'); }));
$('#dismissJob').addEventListener('click', () => { ui.dismissed = jobKey(S.job); renderJob(); });

/* uploads */
async function upload(files) {
  files = [...files];
  if (!files.length) return;
  if (!await settleDraft()) return;
  if (runningHere()) throw new Error(t('job.busyUpload'));
  if (!batch()) {
    const date = new Date().toLocaleDateString(LANG === 'tr' ? 'tr-TR' : 'en-GB', {day: 'numeric', month: 'long', year: 'numeric'});
    const b = await api('/api/batches', {name: t('batch.defaultName', {date})});
    ui.bid = b.id; S = await api('/api/state', undefined, 'GET');
  }
  const form = new FormData();
  files.forEach(f => form.append('files', f));
  ui.uploading = {loaded: 0, total: 1}; renderJob();
  try {
    const r = await uploadRequest(`/api/batches/${ui.bid}/upload`, form, (loaded, total) => { ui.uploading = {loaded, total}; renderJob(); });
    ui.uploading = null;
    await refresh();
    if (r.added && !ui.sid) ui.sid = batch().scans[0]?.id;
    render();
    toast(t('upload.done', {n: r.added}) + (r.errors.length ? ' ' + r.errors.join(' · ') : ''), r.errors.length ? 'error' : '');
  } finally { ui.uploading = null; renderJob(); }
}
$('#fileInput').addEventListener('change', e => act(async () => { const files = [...e.target.files]; e.target.value = ''; await upload(files); }));

let dragDepth = 0;
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
document.addEventListener('dragenter', e => { if (!hasFiles(e)) return; dragDepth++; $('#dropOverlay').hidden = false; });
document.addEventListener('dragleave', e => { if (!hasFiles(e)) return; if (--dragDepth <= 0) { dragDepth = 0; $('#dropOverlay').hidden = true; } });
document.addEventListener('dragover', e => { if (hasFiles(e)) e.preventDefault(); });
document.addEventListener('drop', e => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth = 0; $('#dropOverlay').hidden = true;
  act(() => upload(e.dataTransfer.files));
});

/* export */
$('#exportTop').addEventListener('click', () => {
  const b = batch(), ok = approvedPairs().length, rest = b.pairs.length - ok;
  $('#exportDir').value = store.get('fm-export-dir') || S.export_default;
  $('#exportCount').textContent = t('export.count', {n: ok}) + (rest ? ' ' + t('export.skipped', {n: rest}) : '');
  $('#exportResult').innerHTML = '';
  const btn = $('#doExport'); btn.disabled = false; btn.textContent = t('export.run');
  $('#exportDialog').showModal();
});
$('#doExport').addEventListener('click', () => act(async () => {
  const btn = $('#doExport'), dir = $('#exportDir').value.trim();
  btn.disabled = true; btn.textContent = t('export.running');
  try {
    S = await api('/api/state', undefined, 'GET');
    const result = await api(`/api/batches/${ui.bid}/export`, {revision: batch().revision, directory: dir});
    store.set('fm-export-dir', dir);
    $('#exportResult').innerHTML = `<div class="success"><b>${esc(t('export.saved', {n: result.files.length}))}</b><code>${esc(result.directory)}</code>
      <div class="btn-row"><button class="btn small" id="revealExport">${esc(t('export.reveal'))}</button><a class="btn small" href="/api/exports/${esc(result.id)}/zip">${esc(t('export.zip'))}</a></div></div>`;
    $('#revealExport').onclick = () => act(() => api(`/api/exports/${result.id}/reveal`, {}));
    btn.textContent = t('export.done');
    render();
  } catch (e) {
    $('#exportResult').innerHTML = `<p class="warn-text" role="alert">${esc(e.message)}</p>`;
    btn.disabled = false; btn.textContent = t('export.retry');
  }
}));

/* API key dialog */
async function keyAction(fn) {
  const buttons = $('#apiDialog').querySelectorAll('button:not([data-close])');
  buttons.forEach(b => { b.disabled = true; });
  try { $('#apiStatus').textContent = await fn(); }
  catch (e) { $('#apiStatus').textContent = e.message; }
  finally { $('#apiKey').value = ''; buttons.forEach(b => { b.disabled = false; }); render(); }
}
$('#apiDialog').addEventListener('close', () => { $('#apiKey').value = ''; });
$('#saveApiKey').onclick = () => keyAction(async () => {
  const key = $('#apiKey').value.trim();
  if (!key) throw new Error(t('api.empty'));
  await api('/api/openrouter/key', {key}); S.api_key_saved = true; return t('api.saved');
});
$('#testApiKey').onclick = () => keyAction(async () => (await api('/api/openrouter/test', {})).message);
$('#deleteApiKey').onclick = () => keyAction(async () => { await api('/api/openrouter/key', {delete: true}); S.api_key_saved = false; return t('api.deleted'); });

/* keyboard: photo review */
document.addEventListener('keydown', e => {
  if (!S || ui.view !== 'photos' || document.querySelector('dialog[open]')) return;
  if (e.target.closest('input,select,textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
  const pairs = batch()?.pairs || [], i = pairs.findIndex(p => p.id === ui.pid);
  const move = d => { const n = pairs[i + d]; if (n) { ui.pid = n.id; render(); scrollToActive(); } };
  if (e.key === 'ArrowRight' || e.key === 'j') { e.preventDefault(); move(1); }
  else if (e.key === 'ArrowLeft' || e.key === 'k') { e.preventDefault(); move(-1); }
  else if (e.key === 'a' && pairOf(ui.pid)?.needs_review && !runningHere()) act(actions.approve);
  else if (e.key === 'r' && !runningHere()) act(actions['rotate-front']);
});

window.addEventListener('beforeunload', e => { if (ui.draft) { e.preventDefault(); e.returnValue = ''; } });

/* polling: fast while a job runs, slow otherwise, paused in background tabs */
const poll = {
  timer: null,
  soon() { clearTimeout(this.timer); this.timer = setTimeout(() => this.tick(), 700); },
  async tick() {
    try {
      if (!document.hidden && S) {
        const next = await api('/api/state', undefined, 'GET');
        const wasRunning = running(), key = jobKey(next.job);
        const changed = key !== ui.jobSeen || JSON.stringify(next.batches.map(b => b.revision)) !== JSON.stringify(S.batches.map(b => b.revision));
        S = next;
        if (changed) {
          ui.jobSeen = key;
          if (wasRunning && next.job.status === 'done' && next.job.batch_id === ui.bid) { ui.view = 'photos'; ui.filter = 'all'; }
          // Re-render only when not interacting with a text field, so typing is never lost.
          if (!document.activeElement?.matches('input,textarea') || wasRunning !== running()) render();
          else { renderJob(); renderTop(); }
        }
      }
    } catch { /* server restarting; try again */ }
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.tick(), running() ? 1000 : 5000);
  },
};
document.addEventListener('visibilitychange', () => { if (!document.hidden) poll.soon(); });

act(async () => { await refresh(); if (batch()?.pairs.length) { ui.view = 'photos'; render(); } poll.soon(); });
