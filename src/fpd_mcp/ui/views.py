"""MCP App HTML views for USPTO FPD MCP.

Two views, adapted from the PTAB/PFW reference implementations:
- SEARCH_RESULTS_HTML: one view for the five petition search/details tools;
  renders petitionDecisionDataBag records as cards with decision/type
  filters, Google Patents and Patent Center buttons.
- DOWNLOADS_HTML: recent downloads panel fed primarily by ontoolresult
  (iframes cannot fetch() localhost — Lesson 23); /api/recent-downloads
  fetch is a secondary Refresh path only.
"""

# ---------------------------------------------------------------------------
# View 1: Search Results (used by the petition search/details tools)
# ---------------------------------------------------------------------------

SEARCH_RESULTS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FPD Petition Search Results</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; background: #f8f9fa; color: #1a1a2e; }

.header { background: #1e4d5c; color: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 14px; font-weight: 600; }
.header .badge { background: #3d8ba3; border-radius: 4px; padding: 2px 7px; font-size: 11px; }
.summary-bar { background: #e6f2f6; border-bottom: 1px solid #c2dde6; padding: 7px 14px; font-size: 12px; color: #1e4d5c; display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.summary-bar span { font-weight: 600; }

.filter-bar { background: #f2f8fa; border: 1px solid #c2dde6; border-radius: 6px; margin: 8px 14px 0; padding: 7px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.sort-bar { background: #f2f8fa; border: 1px solid #c2dde6; border-radius: 6px; margin: 6px 14px 0; padding: 5px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.field-notice { background: #fffbe6; border-bottom: 1px solid #ffe58f; padding: 5px 14px; font-size: 11px; color: #7d5a00; line-height: 1.5; }
.filter-label { font-size: 10px; color: #888; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; margin-right: 2px; }
.pill { border: 1px solid #c2dde6; border-radius: 12px; padding: 2px 9px; font-size: 11px; font-weight: 700; cursor: pointer; background: #fff; color: #1e4d5c; transition: all 0.12s; user-select: none; }
.pill:hover { border-color: #3d8ba3; background: #e6f2f6; }
.pill.active { background: #1e4d5c; color: #fff; border-color: #1e4d5c; }
.pill-count { font-size: 9px; font-weight: 700; background: #e6f2f6; color: #1e4d5c; border-radius: 8px; padding: 0 4px; margin-left: 3px; }
.pill.active .pill-count { background: rgba(255,255,255,0.25); }
.sort-pill { border: 1px solid #c2dde6; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 600; cursor: pointer; background: #fff; color: #555; transition: all 0.12s; user-select: none; }
.sort-pill:hover { border-color: #3d8ba3; background: #e6f2f6; color: #1e4d5c; }
.sort-pill.active { background: #1e4d5c; color: #fff; border-color: #1e4d5c; }
.filter-result { font-size: 11px; color: #888; margin-left: auto; }
.clear-link { font-size: 11px; color: #c0392b; cursor: pointer; text-decoration: underline; display: none; }

.container { padding: 10px 14px; }
.card { background: #fff; border: 1px solid #d8e4e8; border-radius: 6px; margin-bottom: 8px; padding: 10px 12px; }
.card:hover { border-color: #3d8ba3; box-shadow: 0 1px 4px rgba(61,139,163,0.15); }
.card.hidden { display: none; }
.pet-id { font-size: 11px; color: #3d8ba3; font-weight: 700; font-family: monospace; }
.card-title { font-weight: 600; font-size: 13px; margin: 4px 0 5px; }
.meta { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 4px 12px; font-size: 11px; margin-top: 6px; }
.meta-item { display: flex; flex-direction: column; }
.meta-label { color: #888; font-size: 10px; text-transform: uppercase; letter-spacing: 0.3px; }
.meta-val { color: #1a1a2e; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actions { margin-top: 7px; display: flex; gap: 6px; flex-wrap: wrap; }
.btn { display: inline-block; border: none; border-radius: 4px; padding: 3px 9px; font-size: 11px; cursor: pointer; }
.btn-primary { background: #1e4d5c; color: #fff; }
.btn-primary:hover { background: #3d8ba3; }
.btn-secondary { background: #e6f2f6; color: #1e4d5c; border: 1px solid #c2dde6; }
.btn-secondary:hover { background: #c2dde6; }
.decision-badge { display: inline-block; border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 700; margin-left: 6px; }
.decision-GRANTED { background: #276749; color: #fff; }
.decision-GRANTED-IN-PART { background: #2c7a7b; color: #fff; }
.decision-DENIED { background: #9b2c2c; color: #fff; }
.decision-DISMISSED { background: #4a5568; color: #fff; }
.decision-OTHER { background: #718096; color: #fff; }
.type-badge { display: inline-block; border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 600; background: #e6f2f6; color: #1e4d5c; margin-left: 6px; }

#loading { text-align: center; padding: 30px; color: #666; }
#error { background: #fde8e8; border: 1px solid #f5c6cb; color: #721c24; padding: 10px 14px; margin: 10px 14px; border-radius: 4px; }
.no-match { text-align: center; padding: 20px; color: #888; font-size: 12px; display: none; }
</style>
</head>
<body>
<div class="header">
  <h1>FPD Petition Decisions</h1>
  <span class="badge" id="tier-badge">—</span>
</div>
<div class="summary-bar" id="summary-bar" style="display:none"></div>
<div class="field-notice" id="field-notice" style="display:none"><strong>Note:</strong> Fields showing <strong>"—"</strong> were not requested in this tool call. The LLM selects fields to balance context efficiency.</div>
<div class="filter-bar" id="filter-bar" style="display:none"></div>
<div class="sort-bar" id="sort-bar" style="display:none"></div>
<div id="loading">Waiting for search results...</div>
<div id="error" style="display:none"></div>
<div class="container" id="content" style="display:none">
  <div id="cards"></div>
  <div class="no-match" id="no-match">No results match the selected filters.</div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const app = new App({ name: 'FPD Petition Search Results', version: '1.0.0' });

let allDocs = [];
let cardEls = [];
let activeFilters = {};
let currentSort = null;

app.ontoolresult = (result) => {
  const text = result.content?.find(c => c.type === 'text')?.text;
  try {
    let data = JSON.parse(text);
    if (data && typeof data === 'object' && typeof data.result === 'string') {
      try { data = JSON.parse(data.result); } catch (unwrapErr) { /* keep wrapper */ }
    }
    render(data);
  }
  catch(e) { showError('Could not parse search results: ' + e.message); }
};

app.connect();

// M-12: USPTO applicant names, invention titles and decision-type text are
// applicant-authored free text and every card below is built with innerHTML.
// Same helper as ui/user_management_view.py, which had it and used it.
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

const d = (v) => (v ? String(v).split('T')[0] : '');

// Normalize a petitionDecisionDataBag record into the card model.
function normalize(rec) {
  const decisionRaw = rec.decisionTypeCodeDescriptionText || '';
  return {
    id: rec.petitionDecisionRecordIdentifier || '—',
    title: rec.inventionTitle || '',
    decision: decisionRaw,
    decisionClass: decisionClass(decisionRaw),
    petType: rec.decisionPetitionTypeCodeDescriptionText || rec.decisionPetitionTypeCode || '',
    applicant: rec.firstApplicantName || '—',
    appNum: rec.applicationNumberText || '',
    patentNum: rec.patentNumber || '',
    artUnit: rec.groupArtUnitNumber || '',
    tc: rec.technologyCenter || '',
    office: rec.finalDecidingOfficeName || '',
    mailed: d(rec.petitionMailDate),
    decided: d(rec.decisionDate),
    rules: Array.isArray(rec.ruleBag) ? rec.ruleBag.join(', ') : '',
  };
}

function decisionClass(decision) {
  const u = String(decision).toUpperCase();
  if (u.includes('GRANTED-IN-PART') || u.includes('GRANTED IN PART')) return 'GRANTED-IN-PART';
  if (u.includes('GRANTED')) return 'GRANTED';
  if (u.includes('DENIED')) return 'DENIED';
  if (u.includes('DISMISSED')) return 'DISMISSED';
  return 'OTHER';
}

function render(data) {
  document.getElementById('loading').style.display = 'none';
  if (data.error || data.status === 'error') { showError(data.message || data.error || 'API error'); return; }

  const records = data.petitionDecisionDataBag || data.results || [];
  allDocs = records.map(normalize);
  activeFilters = {};
  currentSort = null;

  const total = data.count ?? allDocs.length;
  const tier = data.query_info?.tier || 'search';
  document.getElementById('tier-badge').textContent = String(tier).toUpperCase();

  const bar = document.getElementById('summary-bar');
  bar.style.display = 'flex';
  bar.innerHTML = `
    <div>Found: <span>${Number(total).toLocaleString()}</span> petitions</div>
    <div>Showing: <span>${allDocs.length}</span></div>
  `;

  document.getElementById('field-notice').style.display = String(tier).includes('minimal') ? 'block' : 'none';

  const cardsEl = document.getElementById('cards');
  cardsEl.innerHTML = '';
  cardEls = [];
  if (allDocs.length === 0) {
    cardsEl.innerHTML = '<div style="text-align:center;padding:24px;color:#888">No petition decisions found.</div>';
  } else {
    allDocs.forEach(p => {
      const el = buildCard(p);
      cardsEl.appendChild(el);
      cardEls.push(el);
    });
  }

  buildFilterBar();
  buildSortBar();
  document.getElementById('content').style.display = 'block';
}

// US patent number gate for the Google Patents button (Lesson 26):
// plain 6-8 digit utility numbers or RE reissues; excludes empty/odd values.
function googlePatentsUrl(patentNum) {
  const clean = String(patentNum).replace(/[,\/]/g, '').trim();
  if (!/^(RE)?\d{6,8}$/i.test(clean)) return null;
  return `https://patents.google.com/patent/US${encodeURIComponent(clean.toUpperCase())}`;
}

function buildCard(p) {
  const div = document.createElement('div');
  div.className = 'card';

  div.dataset.decision = p.decisionClass;
  div.dataset.pettype = p.petType || '';
  div.dataset.applicant = p.applicant || '';
  div.dataset.office = p.office || '';
  div.dataset.mailed = p.mailed || '';
  div.dataset.decided = p.decided || '';
  div.dataset.applicantsort = (p.applicant || '').toLowerCase();
  div.dataset.patentnum = p.patentNum || '';

  const gpUrl = googlePatentsUrl(p.patentNum);
  const appNumClean = String(p.appNum || '').replace(/[,\/]/g, '');

  div.innerHTML = `
    <div class="pet-id">${esc(p.id)}${p.decision ? `<span class="decision-badge decision-${esc(p.decisionClass)}">${esc(p.decision)}</span>` : ''}${p.petType ? `<span class="type-badge" title="${esc(p.petType)}">${esc(p.petType.length > 44 ? p.petType.slice(0, 42) + '…' : p.petType)}</span>` : ''}</div>
    ${p.title ? `<div class="card-title" title="${esc(p.title)}">${esc(p.title)}</div>` : ''}
    <div class="meta">
      <div class="meta-item"><span class="meta-label">Applicant</span><span class="meta-val" title="${esc(p.applicant)}">${esc(p.applicant)}</span></div>
      <div class="meta-item"><span class="meta-label">Petition Mailed</span><span class="meta-val">${esc(p.mailed) || '—'}</span></div>
      <div class="meta-item"><span class="meta-label">Decided</span><span class="meta-val">${esc(p.decided) || '—'}</span></div>
      ${p.appNum ? `<div class="meta-item"><span class="meta-label">Application</span><span class="meta-val">${esc(p.appNum)}</span></div>` : ''}
      ${p.patentNum ? `<div class="meta-item"><span class="meta-label">Patent</span><span class="meta-val">${esc(p.patentNum)}</span></div>` : ''}
      ${p.artUnit ? `<div class="meta-item"><span class="meta-label">Art Unit</span><span class="meta-val">${esc(p.artUnit)}</span></div>` : ''}
      ${p.tc ? `<div class="meta-item"><span class="meta-label">Tech Center</span><span class="meta-val">${esc(p.tc)}</span></div>` : ''}
      ${p.office ? `<div class="meta-item"><span class="meta-label">Deciding Office</span><span class="meta-val" title="${esc(p.office)}">${esc(p.office)}</span></div>` : ''}
      ${p.rules ? `<div class="meta-item"><span class="meta-label">Rules</span><span class="meta-val" title="${esc(p.rules)}">${esc(p.rules)}</span></div>` : ''}
    </div>
    <div class="actions">
      ${gpUrl ? `<button class="btn btn-primary" data-gp="${esc(gpUrl)}">Google Patents →</button>` : ''}
      ${appNumClean ? `<button class="btn btn-secondary" data-app="${esc(appNumClean)}">Patent Center →</button>` : ''}
    </div>
  `;

  div.querySelector('[data-gp]')?.addEventListener('click', async () => {
    try { await app.openLink({ url: gpUrl }); } catch { window.open(gpUrl, '_blank'); }
  });
  div.querySelector('[data-app]')?.addEventListener('click', async () => {
    const url = `https://patentcenter.uspto.gov/applications/${appNumClean}`;
    try { await app.openLink({ url }); } catch { window.open(url, '_blank'); }
  });

  return div;
}

function buildFilterBar() {
  const bar = document.getElementById('filter-bar');
  if (allDocs.length < 2) { bar.style.display = 'none'; return; }

  const decisions = countBy(p => p.decisionClass, v => !!v);
  const petTypes = countBy(p => p.petType, v => !!v);
  const applicants = countBy(p => p.applicant, v => !!v && v !== '—');
  const offices = countBy(p => p.office, v => !!v);

  bar.style.display = 'flex';
  bar.innerHTML = '';
  let hasAnyFilter = false;

  if (Object.keys(decisions).length > 1) {
    hasAnyFilter = true;
    appendLabel(bar, 'Decision:');
    Object.entries(decisions).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'decision', val));
    });
  }

  if (Object.keys(petTypes).length > 1 && Object.keys(petTypes).length <= 6) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Type:');
    Object.entries(petTypes).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      const label = val.length > 34 ? val.slice(0, 32) + '…' : val;
      bar.appendChild(makePill(label, count, 'pettype', val));
    });
  }

  // Applicant filter: pills only for applicants appearing >= 2 times
  const frequentApplicants = Object.fromEntries(Object.entries(applicants).filter(([,c]) => c >= 2));
  if (Object.keys(frequentApplicants).length >= 1 && Object.keys(frequentApplicants).length <= 6) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Applicant:');
    Object.entries(frequentApplicants).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'applicant', val));
    });
  }

  const frequentOffices = Object.fromEntries(Object.entries(offices).filter(([,c]) => c >= 2));
  if (Object.keys(frequentOffices).length > 1 && Object.keys(frequentOffices).length <= 5) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Office:');
    Object.entries(frequentOffices).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      const label = val.length > 30 ? val.slice(0, 28) + '…' : val;
      bar.appendChild(makePill(label, count, 'office', val));
    });
  }

  if (!hasAnyFilter) { bar.style.display = 'none'; return; }

  const counter = document.createElement('span');
  counter.className = 'filter-result';
  counter.id = 'filter-result';
  bar.appendChild(counter);

  const clearLink = document.createElement('a');
  clearLink.className = 'clear-link';
  clearLink.id = 'clear-link';
  clearLink.textContent = '× Clear';
  clearLink.addEventListener('click', clearFilters);
  bar.appendChild(clearLink);
}

function appendLabel(bar, text) {
  const lbl = document.createElement('span');
  lbl.className = 'filter-label';
  lbl.textContent = text;
  bar.appendChild(lbl);
}

function appendSep(bar) {
  const sep = document.createElement('div');
  sep.style.cssText = 'width:1px;background:#d8e4e8;height:18px;margin:0 4px;align-self:center;flex-shrink:0;';
  bar.appendChild(sep);
}

function buildSortBar() {
  const bar = document.getElementById('sort-bar');
  if (allDocs.length < 2) { bar.style.display = 'none'; return; }

  const hasData = (key) => cardEls.some(el => el.dataset[key] && el.dataset[key] !== '—' && el.dataset[key] !== '');
  const sortOptions = [
    { label: 'Mailed', key: 'mailed' },
    { label: 'Decided', key: 'decided' },
    { label: 'Applicant', key: 'applicantsort' },
    { label: 'Patent #', key: 'patentnum' },
  ].filter(opt => hasData(opt.key));

  if (sortOptions.length < 2) { bar.style.display = 'none'; return; }

  bar.style.display = 'flex';
  bar.innerHTML = '';
  appendLabel(bar, 'Sort:');

  sortOptions.forEach(({ label, key }) => {
    const pill = document.createElement('span');
    pill.className = 'sort-pill';
    pill.textContent = label;
    pill.dataset.sortkey = key;
    pill.addEventListener('click', () => {
      document.querySelectorAll('.sort-pill').forEach(p => p.classList.remove('active'));
      if (currentSort === key) {
        currentSort = null;
        renderCardsInOrder(allDocs);
      } else {
        currentSort = key;
        pill.classList.add('active');
        const sorted = [...allDocs].sort((a, b) => {
          const aEl = cardEls[allDocs.indexOf(a)];
          const bEl = cardEls[allDocs.indexOf(b)];
          const aVal = (aEl?.dataset[key] || '').toLowerCase();
          const bVal = (bEl?.dataset[key] || '').toLowerCase();
          return aVal.localeCompare(bVal, undefined, { numeric: key === 'patentnum' });
        });
        renderCardsInOrder(sorted);
      }
    });
    bar.appendChild(pill);
  });
}

function renderCardsInOrder(orderedDocs) {
  const cardsEl = document.getElementById('cards');
  cardsEl.innerHTML = '';
  orderedDocs.forEach(p => {
    const idx = allDocs.indexOf(p);
    if (idx >= 0 && cardEls[idx]) cardsEl.appendChild(cardEls[idx]);
  });
  applyFilters();
}

function makePill(label, count, dim, val) {
  const pill = document.createElement('span');
  pill.className = 'pill';
  pill.dataset.dim = dim;
  pill.dataset.val = val;
  pill.innerHTML = `${esc(label)} <span class="pill-count">${Number(count)}</span>`;
  pill.addEventListener('click', () => {
    if (activeFilters[dim] === val) {
      activeFilters[dim] = null;
      pill.classList.remove('active');
    } else {
      document.querySelectorAll(`.pill[data-dim="${dim}"]`).forEach(p => p.classList.remove('active'));
      activeFilters[dim] = val;
      pill.classList.add('active');
    }
    applyFilters();
  });
  return pill;
}

function countBy(fn, filterFn = () => true) {
  const map = {};
  allDocs.forEach(d => {
    const v = fn(d);
    if (filterFn(v)) map[v] = (map[v] || 0) + 1;
  });
  return map;
}

function applyFilters() {
  let visible = 0;
  cardEls.forEach((el) => {
    const show =
      (!activeFilters.decision  || el.dataset.decision  === activeFilters.decision) &&
      (!activeFilters.pettype   || el.dataset.pettype   === activeFilters.pettype) &&
      (!activeFilters.applicant || el.dataset.applicant === activeFilters.applicant) &&
      (!activeFilters.office    || el.dataset.office    === activeFilters.office);
    el.classList.toggle('hidden', !show);
    if (show) visible++;
  });
  document.getElementById('no-match').style.display = visible === 0 ? 'block' : 'none';
  const counter = document.getElementById('filter-result');
  const clearEl = document.getElementById('clear-link');
  const hasFilter = Object.values(activeFilters).some(Boolean);
  if (counter) counter.textContent = hasFilter ? `${visible} of ${allDocs.length} shown` : '';
  if (clearEl) clearEl.style.display = hasFilter ? 'inline' : 'none';
}

function clearFilters() {
  activeFilters = {};
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  cardEls.forEach(el => el.classList.remove('hidden'));
  document.getElementById('no-match').style.display = 'none';
  const counter = document.getElementById('filter-result');
  const clearEl = document.getElementById('clear-link');
  if (counter) counter.textContent = '';
  if (clearEl) clearEl.style.display = 'none';
}

function showError(msg) {
  document.getElementById('loading').style.display = 'none';
  const el = document.getElementById('error');
  el.style.display = 'block';
  el.textContent = 'Error: ' + msg;
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# View 2: Recent Downloads panel (used by FPD_get_document_download)
# ---------------------------------------------------------------------------

DOWNLOADS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Recent Downloads</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; background: #f8f9fa; color: #1a1a2e; }

.header { background: #1e4d5c; color: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 14px; font-weight: 600; }
.header .count { background: #3d8ba3; border-radius: 4px; padding: 2px 7px; font-size: 11px; }
.header .refresh-btn { margin-left: auto; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); color: #fff; border-radius: 4px; padding: 3px 8px; font-size: 11px; cursor: pointer; }
.header .refresh-btn:hover { background: rgba(255,255,255,0.25); }

.tip { background: #fff9e6; border-bottom: 1px solid #ffe08a; padding: 5px 14px; font-size: 11px; color: #6b5000; }

.container { padding: 10px 14px; }

.empty-state { text-align: center; padding: 40px 20px; color: #888; }
.empty-icon { font-size: 32px; margin-bottom: 8px; }
.empty-text { font-size: 13px; }
.empty-hint { font-size: 11px; color: #aaa; margin-top: 4px; }

.doc-card { background: #fff; border: 1px solid #d8e4e8; border-radius: 6px; margin-bottom: 8px; padding: 10px 12px; display: flex; align-items: flex-start; gap: 10px; }
.doc-card:hover { border-color: #3d8ba3; box-shadow: 0 1px 4px rgba(61,139,163,0.12); }

.doc-icon { width: 32px; height: 32px; border-radius: 4px; background: #e6f2f6; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.doc-info { flex: 1; min-width: 0; }
.doc-title { font-weight: 600; font-size: 12px; margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-meta { font-size: 11px; color: #888; display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 5px; }
.doc-type-badge { display: inline-block; background: #e6f2f6; color: #1e4d5c; border-radius: 3px; padding: 1px 5px; font-size: 10px; font-weight: 700; }
.doc-actions { display: flex; gap: 6px; }
.btn { border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.btn-download { background: #1e4d5c; color: #fff; text-decoration: none; display: inline-block; }
.btn-download:hover { background: #3d8ba3; }

.timestamp { font-size: 10px; color: #bbb; margin-left: auto; white-space: nowrap; align-self: center; }

#status { font-size: 11px; color: #888; text-align: center; padding: 6px; }
</style>
</head>
<body>
<div class="header">
  <h1>Recent Downloads</h1>
  <span class="count" id="count-badge">0</span>
  <button class="refresh-btn" onclick="loadDownloads()">↻ Refresh</button>
</div>
<div class="tip">Click Download to open a document in your browser. Links are valid for 7 days.</div>
<div id="status"></div>
<div class="container" id="content">
  <div class="empty-state" id="empty-state">
    <div class="empty-icon">📂</div>
    <div class="empty-text">No recent downloads yet</div>
    <div class="empty-hint">Use FPD_get_document_download to generate links</div>
  </div>
  <div id="cards"></div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const app = new App({ name: 'FPD Recent Downloads', version: '1.0.0' });

// In-session download store — populated directly from tool results (no fetch needed)
let sessionDownloads = [];
// proxyBaseUrl: derived from the first download_url seen in a tool result so
// it also works behind Docker/reverse proxies (FPD_PROXY_BASE_URL) and the
// PFW centralized proxy.
let proxyBaseUrl = 'http://localhost:8081';

app.ontoolresult = (result) => {
  try {
    const text = result.content?.find(c => c.type === 'text')?.text;
    let data = JSON.parse(text);
    if (data && typeof data === 'object' && typeof data.result === 'string') {
      try { data = JSON.parse(data.result); } catch (unwrapErr) { /* keep wrapper */ }
    }
    const now = new Date().toISOString();

    // FPD_get_document_download result shape
    if (data.download_url && data.document_identifier) {
      const newDoc = {
        title: data.enhanced_filename || 'Document',
        petition_id: data.petition_id || '',
        proxy_url: data.download_url,
        generated_at: now,
      };
      const baseMatch = data.download_url.match(/^(https?:\/\/[^/]+)/);
      if (baseMatch) proxyBaseUrl = baseMatch[1];

      sessionDownloads = [newDoc, ...sessionDownloads].slice(0, 10);
      renderDownloads(sessionDownloads);
      document.getElementById('status').textContent = '';
      return;
    }
  } catch {}
  // No directly parseable downloads — try proxy fetch as fallback
  loadDownloads();
};

app.connect();

// M-12: USPTO applicant names, invention titles and decision-type text are
// applicant-authored free text and every card below is built with innerHTML.
// Same helper as ui/user_management_view.py, which had it and used it.
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Delegated click handler — use app.openLink() so Claude Desktop opens the
// URL in the system browser, bypassing iframe sandbox restrictions (Lesson 24).
document.getElementById('cards').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-url]');
  if (!btn) return;
  const url = btn.dataset.url;
  if (!url) return;
  try {
    await app.openLink({ url });
  } catch {
    // Fallback for hosts that don't support openLink
    window.open(url, '_blank');
  }
});

window.loadDownloads = async function() {
  const statusEl = document.getElementById('status');
  statusEl.textContent = 'Refreshing...';
  try {
    const resp = await fetch(`${proxyBaseUrl}/api/recent-downloads`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    const docs = (body.downloads || []).map(d => ({
      title: d.enhanced_filename || d.document_description || 'Document',
      petition_id: d.petition_id || '',
      proxy_url: d.download_url,
      generated_at: d.registered_at,
    }));
    // Merge proxy results with session store, deduplicate by proxy_url
    const seen = new Set(sessionDownloads.map(d => d.proxy_url));
    const merged = [...sessionDownloads, ...docs.filter(d => !seen.has(d.proxy_url))].slice(0, 10);
    sessionDownloads = merged;
    renderDownloads(sessionDownloads);
    statusEl.textContent = '';
  } catch (e) {
    // Proxy fetch failed (CSP/CORS/not running) — show what we have from session
    renderDownloads(sessionDownloads);
    statusEl.textContent = sessionDownloads.length === 0 ? `Generate a download to see links here.` : '';
  }
};

function renderDownloads(docs) {
  const countBadge = document.getElementById('count-badge');
  const emptyState = document.getElementById('empty-state');
  const cardsEl = document.getElementById('cards');

  countBadge.textContent = docs.length;
  emptyState.style.display = docs.length === 0 ? 'block' : 'none';
  cardsEl.innerHTML = '';

  docs.forEach(doc => cardsEl.appendChild(buildCard(doc)));
}

function buildCard(doc) {
  const div = document.createElement('div');
  div.className = 'doc-card';

  const time = doc.generated_at ? formatTime(doc.generated_at) : '';

  div.innerHTML = `
    <div class="doc-icon">📋</div>
    <div class="doc-info">
      <div class="doc-title" title="${esc(doc.title)}">${esc(doc.title) || 'Document'}</div>
      <div class="doc-meta">
        <span class="doc-type-badge">petition</span>
        <span>${esc(doc.petition_id) || '—'}</span>
      </div>
      <div class="doc-actions">
        <button class="btn btn-download" data-url="${esc(doc.proxy_url)}">Download PDF</button>
      </div>
    </div>
    ${time ? `<div class="timestamp">${esc(time)}</div>` : ''}
  `;

  return div;
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return d.toLocaleDateString();
  } catch { return ''; }
}
</script>
</body>
</html>"""
