// ── Constants ───────────────────────────────────────────────────────────────

const REC_TYPES = [
  { value: 'over_time',     label: 'Over time' },
  { value: 'point_in_time', label: 'Point-in-time' },
  { value: 'upfront',       label: 'Upfront (day 1)' },
  { value: 'usage_based',   label: 'Usage-based' },
];

const SSP_SOURCES = [
  { value: 'observable',                label: 'Observable' },
  { value: 'adjusted_market',           label: 'Adjusted market' },
  { value: 'expected_cost_plus_margin', label: 'Cost + margin' },
  { value: 'residual',                  label: 'Residual' },
];

const REC_LABELS = Object.fromEntries(REC_TYPES.map(t => [t.value, t.label]));
const SSP_LABELS = Object.fromEntries(SSP_SOURCES.map(s => [s.value, s.label]));

const STEP_TITLES = {
  1: 'Identify the Contract',
  2: 'Identify Performance Obligations',
  3: 'Determine Transaction Price',
  4: 'Allocate Transaction Price',
  5: 'Recognize Revenue',
};

// ── State ────────────────────────────────────────────────────────────────────

let _examples   = [];
let _currentData = null;
let _pobIndices = [0];
let _payIndices = [0];
let _pobCounter = 1;
let _payCounter = 1;
let _scrollObserver = null;

// ── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setDefaultDates();
  addPOBRow(0);
  addPaymentRow(0);
  fetchExamples();
  document.getElementById('btn-load').addEventListener('click', onLoadExample);
  document.getElementById('btn-build').addEventListener('click', onBuildCalculate);
  // Prevent scroll wheel from silently changing number inputs while scrolling the sidebar
  document.getElementById('panel-build').addEventListener('wheel', e => {
    if (e.target.type === 'number') e.preventDefault();
  }, { passive: false });
});

// ── Tabs ─────────────────────────────────────────────────────────────────────

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.querySelector(`.tab[data-tab="${name}"]`).classList.add('active');
  document.getElementById(`panel-${name}`).classList.remove('hidden');
}

function setupTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });
}

// ── Sidebar: input ↔ results nav ─────────────────────────────────────────────

function showInputSidebar() {
  document.getElementById('sidebar-input').classList.remove('hidden');
  document.getElementById('sidebar-results').classList.add('hidden');
}

function showResultsSidebar(contract, result) {
  document.getElementById('sidebar-input').classList.add('hidden');
  const el = document.getElementById('sidebar-results');
  el.classList.remove('hidden');

  const parties = contract.vendor && contract.customer
    ? `${contract.vendor} → ${contract.customer}`
    : contract.vendor || contract.customer || result.summary.contract_id;

  el.innerHTML = `
    <div class="nav-section-label">Contract</div>
    <div style="padding:4px 8px 12px;font-size:13px;font-weight:600;color:var(--text);line-height:1.35">${parties}</div>

    <div class="nav-section-label">Results</div>
    <button class="nav-item active" data-section="timeline" onclick="navTo('timeline', this)">
      Recognition timeline
    </button>
    <button class="nav-item" data-section="position" onclick="navTo('position', this)">
      Current position
    </button>

    <div class="nav-section-label" style="margin-top:14px">Audit trail</div>
    ${[1,2,3,4,5].map(n => `
      <button class="nav-item" data-section="step-${n}" onclick="navTo('step-${n}', this)">
        <div class="nav-status spin" id="nav-status-${n}"></div>
        ${n} · ${STEP_TITLES[n]}
      </button>
    `).join('')}

    <div class="nav-section-label" style="margin-top:14px">Outputs</div>
    <button class="nav-item" data-section="outputs" onclick="navTo('outputs', this)">
      Balance sheet &amp; journal entries
    </button>

    <div class="nav-footer">
      <button class="btn btn-outline btn-full btn-sm" onclick="onEdit()">Edit contract</button>
      <button class="btn btn-outline btn-full btn-sm" onclick="downloadCSV()">Download CSV</button>
    </div>
  `;
}

function navTo(section, el) {
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  el?.classList.add('active');
  const target = document.getElementById(`sec-${section}`);
  const results = document.getElementById('results');
  if (target && results) results.scrollTo({ top: target.offsetTop - 24, behavior: 'smooth' });

  const m = section.match(/^step-(\d+)$/);
  if (m) {
    const num = parseInt(m[1]);
    const body = document.getElementById(`step-body-${num}`);
    if (body && !body.classList.contains('open')) toggleStep(num);
  }
}

function setupScrollSpy() {
  if (_scrollObserver) _scrollObserver.disconnect();
  const results = document.getElementById('results');
  const sections = ['timeline','position','step-1','step-2','step-3','step-4','step-5','outputs'];

  _scrollObserver = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (e.isIntersecting) {
        const id = e.target.id.replace('sec-', '');
        document.querySelectorAll('#sidebar-results .nav-item').forEach(el => {
          el.classList.toggle('active', el.dataset.section === id);
        });
      }
    }
  }, { root: results, threshold: 0.25 });

  sections.forEach(id => {
    const el = document.getElementById(`sec-${id}`);
    if (el) _scrollObserver.observe(el);
  });
}

// ── Examples ──────────────────────────────────────────────────────────────────

async function fetchExamples() {
  _examples = await (await fetch('/api/examples')).json();
  const sel = document.getElementById('example-select');
  sel.innerHTML = _examples.map((ex, i) => `<option value="${i}">${ex.key}</option>`).join('');
  sel.addEventListener('change', renderScenarioCard);
  renderScenarioCard();
}

function renderScenarioCard() {
  const i  = parseInt(document.getElementById('example-select').value, 10);
  const ex = _examples[i];
  if (!ex) return;

  const fields = [];
  if (ex.vendor)                              fields.push({ label: 'Vendor',       value: ex.vendor });
  if (ex.customer)                            fields.push({ label: 'Customer',     value: ex.customer });
  if (ex.industry)                            fields.push({ label: 'Industry',     value: ex.industry });
  if (ex.start_date && ex.end_date)           fields.push({ label: 'Period',       value: fmtDateRange(ex.start_date, ex.end_date) });
  if (ex.total_contract_value)                fields.push({ label: 'Value',        value: fmtShort(ex.total_contract_value) });
  if (ex.num_pobs != null)                    fields.push({ label: 'Obligations',  value: `${ex.num_pobs}` });

  document.getElementById('scenario-card').innerHTML = `
    <div class="sc-field-grid">
      ${fields.map(f => `
        <div class="sc-field">
          <span class="sc-fl">${f.label}</span>
          <span class="sc-fv">${f.value}</span>
        </div>
      `).join('')}
    </div>
  `;
}

async function onLoadExample() {
  const i        = parseInt(document.getElementById('example-select').value, 10);
  const contract = await (await fetch(`/api/examples/${i}`)).json();
  await calculate(contract);
}

// ── Build form ────────────────────────────────────────────────────────────────

function setDefaultDates() {
  const y = new Date().getFullYear();
  document.getElementById('b-start').value = `${y}-01-01`;
  document.getElementById('b-end').value   = `${y + 1}-12-31`;
}

function addPOB() {
  const idx = _pobCounter++;
  _pobIndices.push(idx);
  addPOBRow(idx);
  updateFormButtons();
}

function removePOB() {
  if (_pobIndices.length <= 1) return;
  const idx = _pobIndices.pop();
  document.getElementById(`pob-${idx}`)?.remove();
  updateFormButtons();
}

function addPOBRow(idx) {
  const div = document.createElement('div');
  div.className = 'pob-card';
  div.id = `pob-${idx}`;
  div.innerHTML = `
    <div class="pob-label" id="pob-label-${idx}">POB ${_pobIndices.indexOf(idx) + 1}</div>
    <div class="form-field">
      <label>Name</label>
      <input type="text" class="input" id="p-name-${idx}" placeholder="e.g. SaaS Platform Access" />
    </div>
    <div class="form-row">
      <div class="form-field">
        <label>Recognition type</label>
        <select class="select" id="p-rec-${idx}" onchange="toggleCompletionDate(${idx})">
          ${REC_TYPES.map(t => `<option value="${t.value}">${t.label}</option>`).join('')}
        </select>
      </div>
      <div class="form-field">
        <label>SSP ($)</label>
        <input type="number" class="input" id="p-ssp-${idx}" min="0" step="1000" value="0" />
      </div>
    </div>
    <div class="form-field">
      <label>SSP Source</label>
      <select class="select" id="p-src-${idx}">
        ${SSP_SOURCES.map(s => `<option value="${s.value}">${s.label}</option>`).join('')}
      </select>
    </div>
    <div class="form-field hidden" id="p-date-wrap-${idx}">
      <label>Completion Date</label>
      <input type="date" class="input" id="p-date-${idx}" />
    </div>
  `;
  document.getElementById('pob-container').appendChild(div);
}

function toggleCompletionDate(idx) {
  const rec = document.getElementById(`p-rec-${idx}`)?.value;
  document.getElementById(`p-date-wrap-${idx}`)?.classList.toggle('hidden', rec !== 'point_in_time');
}

function addPayment() {
  const idx = _payCounter++;
  _payIndices.push(idx);
  addPaymentRow(idx);
  updateFormButtons();
}

function removePayment() {
  if (_payIndices.length <= 1) return;
  const idx = _payIndices.pop();
  document.getElementById(`pay-${idx}`)?.remove();
  updateFormButtons();
}

function addPaymentRow(idx) {
  const div = document.createElement('div');
  div.className = 'pay-row';
  div.id = `pay-${idx}`;
  const start = document.getElementById('b-start')?.value || '';
  div.innerHTML = `
    <div class="form-field">
      <label>Invoice Date</label>
      <input type="date" class="input" id="pay-dt-${idx}" value="${start}" />
    </div>
    <div class="form-field">
      <label>Amount ($)</label>
      <input type="number" class="input" id="pay-amt-${idx}" min="0" step="1000" value="0" />
    </div>
  `;
  document.getElementById('payment-container').appendChild(div);
}

function updateFormButtons() {
  document.getElementById('btn-rem-pob').disabled = _pobIndices.length <= 1;
  document.getElementById('btn-rem-pay').disabled = _payIndices.length <= 1;
  _pobIndices.forEach((idx, i) => {
    const el = document.getElementById(`pob-label-${idx}`);
    if (el) el.textContent = `POB ${i + 1}`;
  });
}

function buildContractFromForm() {
  const errors   = [];
  const id       = document.getElementById('b-id').value.trim() || 'C-NEW';
  const currency = document.getElementById('b-currency').value;
  const start    = document.getElementById('b-start').value;
  const end      = document.getElementById('b-end').value;
  const tcv      = parseFloat(document.getElementById('b-tcv').value) || 0;

  if (!start || !end || start >= end) errors.push('End date must be after start date.');
  if (tcv <= 0) errors.push('Contract value must be greater than 0.');

  const pobs = [];
  for (const idx of _pobIndices) {
    const name = (document.getElementById(`p-name-${idx}`)?.value || '').trim();
    if (!name) { errors.push(`POB ${_pobIndices.indexOf(idx) + 1} needs a name.`); continue; }
    const rec   = document.getElementById(`p-rec-${idx}`)?.value || 'over_time';
    const ssp   = parseFloat(document.getElementById(`p-ssp-${idx}`)?.value) || 0;
    const src   = document.getElementById(`p-src-${idx}`)?.value || 'observable';
    const pdate = document.getElementById(`p-date-${idx}`)?.value;
    const ob    = {
      id: `POB-${pobs.length + 1}`, name, recognition_type: rec,
      recognition_params: {},
      ssp: { amount: ssp > 0 ? ssp : null, source: src },
    };
    if (rec === 'point_in_time' && pdate) ob.recognition_params.estimated_completion_date = pdate;
    pobs.push(ob);
  }

  const payments = [];
  for (const idx of _payIndices) {
    const dt  = document.getElementById(`pay-dt-${idx}`)?.value;
    const amt = parseFloat(document.getElementById(`pay-amt-${idx}`)?.value) || 0;
    if (amt > 0 && dt) payments.push({ invoice_date: dt, amount: amt });
  }

  const errDiv = document.getElementById('build-errors');
  if (errors.length) {
    errDiv.classList.remove('hidden');
    errDiv.innerHTML = errors.map(e => `<p>⚠ ${e}</p>`).join('');
    return null;
  }
  errDiv.classList.add('hidden');
  return { contract_id: id, start_date: start, end_date: end, currency,
           total_contract_value: tcv, performance_obligations: pobs, payment_schedule: payments };
}

async function onBuildCalculate() {
  const contract = buildContractFromForm();
  if (contract) await calculate(contract);
}

// ── Edit: pre-fill form from current contract ─────────────────────────────────

function onEdit() {
  const contract = _currentData?.contract;
  if (!contract) return;

  showInputSidebar();
  switchTab('build');

  // Basic fields
  document.getElementById('b-id').value       = contract.contract_id || '';
  document.getElementById('b-currency').value = contract.currency || 'USD';
  document.getElementById('b-start').value    = contract.start_date || '';
  document.getElementById('b-end').value      = contract.end_date || '';
  document.getElementById('b-tcv').value      = contract.total_contract_value || 0;

  // Rebuild POBs
  document.getElementById('pob-container').innerHTML = '';
  _pobIndices = []; _pobCounter = 0;
  const pobs = contract.performance_obligations || [];
  for (let i = 0; i < pobs.length; i++) {
    _pobIndices.push(_pobCounter);
    addPOBRow(_pobCounter++);
    const pob = pobs[i]; const idx = _pobIndices[i];
    document.getElementById(`p-name-${idx}`).value = pob.name || '';
    document.getElementById(`p-rec-${idx}`).value  = pob.recognition_type || 'over_time';
    document.getElementById(`p-ssp-${idx}`).value  = pob.ssp?.amount || 0;
    document.getElementById(`p-src-${idx}`).value  = pob.ssp?.source || 'observable';
    if (pob.recognition_type === 'point_in_time') {
      toggleCompletionDate(idx);
      if (pob.recognition_params?.estimated_completion_date)
        document.getElementById(`p-date-${idx}`).value = pob.recognition_params.estimated_completion_date;
    }
  }

  // Rebuild payments
  document.getElementById('payment-container').innerHTML = '';
  _payIndices = []; _payCounter = 0;
  const payments = contract.payment_schedule || [];
  for (let i = 0; i < payments.length; i++) {
    _payIndices.push(_payCounter);
    addPaymentRow(_payCounter++);
    const pay = payments[i]; const idx = _payIndices[i];
    document.getElementById(`pay-dt-${idx}`).value  = pay.invoice_date || '';
    // "variable" is not a valid number — fall back to the estimated value so the
    // payment survives a round-trip through the build form without being dropped.
    const payAmt = pay.amount === 'variable' ? (pay.estimated || 0) : (pay.amount || 0);
    document.getElementById(`pay-amt-${idx}`).value = payAmt;
  }
  if (payments.length === 0) { _payIndices = [0]; addPaymentRow(0); _payCounter = 1; }

  updateFormButtons();
}

// ── Calculate ─────────────────────────────────────────────────────────────────

async function calculate(contract) {
  const btnLoad  = document.getElementById('btn-load');
  const btnBuild = document.getElementById('btn-build');
  [btnLoad, btnBuild].forEach(b => { if (b) { b.disabled = true; b.classList.add('btn-loading'); } });

  document.getElementById('results').innerHTML = `
    <div class="loading-panel">
      <div class="spinner" style="width:24px;height:24px;border-width:3px"></div>
      <span>Calculating schedule…</span>
    </div>`;

  try {
    const resp = await fetch('/api/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contract }),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail || 'Calculation failed');
    const { result, step_data } = await resp.json();
    _currentData = { contract, result, step_data };

    showResultsSidebar(contract, result);
    renderResults(contract, result, step_data);
    requestAnimationFrame(setupScrollSpy);
    streamReasoning(contract, step_data);
  } catch (e) {
    document.getElementById('results').innerHTML =
      `<div style="padding:40px;color:var(--danger);font-size:14px">Error: ${e.message}</div>`;
  } finally {
    [btnLoad, btnBuild].forEach(b => { if (b) { b.disabled = false; b.classList.remove('btn-loading'); } });
  }
}

// ── Render results ────────────────────────────────────────────────────────────

function renderResults(contract, result, step_data) {
  const { schedule, obligations, summary } = result;
  const asOf = todayStr();

  const vendor   = contract.vendor   || '';
  const customer = contract.customer || '';
  const industry = contract.industry || '';
  const parties  = vendor && customer ? `${vendor} → ${customer}` : vendor || customer || summary.contract_id;

  const n      = summary.num_obligations;
  const sub    = [
    fmtShort(summary.total_contract_value) + ' contract',
    fmtDateRange(contract.start_date, contract.end_date),
    `${n} deliverable${n !== 1 ? 's' : ''}`,
    industry,
  ].filter(Boolean).join(' · ');

  const snap      = snapshotCalc(schedule, asOf);
  const remaining = Math.max(0, summary.total_contract_value - snap.rev_to_date);
  const conclusions = stepConclusions(step_data, result);

  document.getElementById('results').innerHTML = `
    <!-- Header -->
    <div class="contract-header">
      <div>
        <div class="contract-title">${parties}</div>
        <div class="contract-subtitle">${sub}</div>
      </div>
      <div class="header-actions">
        <button class="btn btn-outline btn-sm" onclick="onEdit()">Edit</button>
        <button class="btn btn-outline btn-sm" onclick="downloadCSV()">Export CSV</button>
      </div>
    </div>

    <!-- Recognition timeline -->
    <section id="sec-timeline" class="result-section">
      <div class="section-heading">Recognition Timeline</div>
      <div id="revenue-chart"></div>
    </section>

    <!-- Current position -->
    <section id="sec-position" class="result-section">
      <div class="section-heading">Current Position</div>
      <div class="asof-row">
        <label for="asof-input">As of</label>
        <input type="date" id="asof-input" class="input" value="${asOf}" />
      </div>
      <div id="progress-card">${progressCardHtml(snap, summary, remaining)}</div>
    </section>

    <!-- Audit trail -->
    <div class="audit-divider" style="margin-top:36px">
      <div class="audit-divider-line"></div>
      <div class="audit-divider-text">How we got here</div>
      <div class="audit-divider-line"></div>
    </div>

    ${[1,2,3,4,5].map(n => stepAccordion(n, conclusions[n], step_data, result, obligations)).join('')}

    <!-- Outputs -->
    <div class="audit-divider" style="margin-top:32px">
      <div class="audit-divider-line"></div>
      <div class="audit-divider-text">Outputs</div>
      <div class="audit-divider-line"></div>
    </div>

    <section id="sec-outputs" class="outputs-section">
      <details class="collapsible">
        <summary>Balance Sheet</summary>
        <div class="collapsible-body">
          <div id="balance-chart"></div>
          <p class="caption" style="margin-top:8px">
            <strong>Deferred Revenue</strong> = cumulative billings exceed revenue recognized.
            <strong>Unbilled Revenue</strong> = revenue recognized exceeds billings.
          </p>
        </div>
      </details>
      <details class="collapsible">
        <summary>Journal Entries</summary>
        <div class="collapsible-body">
          <p class="caption" style="margin-bottom:10px">Revenue recognition and billing entries by period.</p>
          ${renderJournalEntries(schedule, obligations)}
        </div>
      </details>
    </section>
  `;

  document.getElementById('asof-input').addEventListener('change', onAsOfChange);
  document.querySelector('#sec-outputs details').addEventListener('toggle', function () {
    if (this.open) renderBalanceChart(result, document.getElementById('asof-input').value);
  });

  requestAnimationFrame(() => renderRevenueChart(result, asOf));
}

// ── Progress card ─────────────────────────────────────────────────────────────

function progressCardHtml(snap, summary, remaining) {
  const total  = summary.total_contract_value || 1;
  const pct    = Math.min(100, (snap.rev_to_date / total) * 100);
  return `
    <div class="progress-card">
      <div class="progress-top">
        <div class="progress-top-label">Revenue recognized</div>
        <div class="progress-pct">${pct.toFixed(0)}%</div>
      </div>
      <div class="progress-track">
        <div class="progress-fill" style="width:${pct}%"></div>
      </div>
      <div class="progress-main">
        <div class="progress-main-item">
          <strong>${fmt(snap.rev_to_date)}</strong>
          <span>recognized · ${snap.periods_complete} of ${summary.duration_months} periods</span>
        </div>
        <div class="progress-main-item" style="text-align:right">
          <strong>${fmt(remaining)}</strong>
          <span>remaining</span>
        </div>
      </div>
      <div class="progress-secondary">
        <span>${fmt(snap.deferred)} deferred revenue</span>
        ${snap.contract_asset > 0 ? `<span>${fmt(snap.contract_asset)} unbilled revenue</span>` : ''}
      </div>
    </div>
  `;
}

function onAsOfChange() {
  if (!_currentData) return;
  const { result } = _currentData;
  const asOf       = document.getElementById('asof-input').value;
  const snap       = snapshotCalc(result.schedule, asOf);
  const remaining  = Math.max(0, result.summary.total_contract_value - snap.rev_to_date);
  document.getElementById('progress-card').innerHTML = progressCardHtml(snap, result.summary, remaining);
  renderRevenueChart(result, asOf);
  if (document.querySelector('#sec-outputs details[open]')) renderBalanceChart(result, asOf);
}

// ── Step accordions ───────────────────────────────────────────────────────────

function stepAccordion(num, conclusion, step_data, result, obligations) {
  const body = stepBody(num, step_data, result, obligations);
  return `
    <section id="sec-step-${num}">
      <div class="step-accordion">
        <div class="step-acc-header" id="step-hdr-${num}" onclick="toggleStep(${num})">
          <div class="step-num">${num}</div>
          <div class="step-header-text">
            <div class="step-title-text">${STEP_TITLES[num]}</div>
            <div class="step-conclusion">${conclusion}</div>
          </div>
          <div class="step-ai-status" id="step-ai-status-${num}">
            <div class="spinner"></div>
          </div>
          <div class="step-chevron">›</div>
        </div>
        <div class="step-acc-body" id="step-body-${num}">
          ${body}
          <div class="ai-badge ai-badge--loading" id="ai-step_${num}">
            <div class="spinner"></div> Generating AI reasoning…
          </div>
        </div>
      </div>
    </section>
  `;
}

function toggleStep(num) {
  const hdr  = document.getElementById(`step-hdr-${num}`);
  const body = document.getElementById(`step-body-${num}`);
  const open = body.classList.contains('open');
  body.classList.toggle('open', !open);
  hdr.classList.toggle('open', !open);
}

function stepBody(num, step_data, result, obligations) {
  switch (num) {
    case 1: return bodyStep1(step_data.step_1);
    case 2: return bodyStep2(step_data.step_2);
    case 3: return bodyStep3(step_data.step_3);
    case 4: return bodyStep4(step_data.step_4);
    case 5: return bodyStep5(step_data.step_5, result);
  }
  return '';
}

function bodyStep1(s1) {
  return `
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-label">Contract ID</div>
        <div class="metric-value metric-value-sm">${s1.contract_id}</div>
      </div>
      <div class="metric-card metric-card--hero">
        <div class="metric-label">Contract Value</div>
        <div class="metric-value">${fmt(s1.total_contract_value)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Term</div>
        <div class="metric-value metric-value-sm">${s1.duration_months} months</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Modifications</div>
        <div class="metric-value metric-value-sm">${s1.has_modifications ? 'Yes' : 'No'}</div>
      </div>
    </div>
    <p class="caption">${fmtDateRange(s1.start_date, s1.end_date)} · ${s1.currency}</p>
  `;
}

function bodyStep2(s2) {
  const headers = ['Obligation', 'Recognition', 'SSP', 'SSP Basis', 'Modification'];
  const rows    = s2.obligations.map(ob => [
    ob.name,
    REC_LABELS[ob.recognition_type] || ob.recognition_type,
    ob.ssp_amount ? fmt(ob.ssp_amount) : 'Residual',
    SSP_LABELS[ob.ssp_source] || ob.ssp_source || '—',
    ob.is_modification ? 'Yes' : '—',
  ]);
  return makeTable(headers, rows);
}

function bodyStep3(s3) {
  const vc = s3.variable_consideration;
  let vcHtml = '';
  if (vc) {
    const method = vc.method.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    vcHtml = `<p style="margin:10px 0 6px;font-size:13px">
      <strong>Variable consideration</strong> — ${method} method &nbsp;·&nbsp;
      constrained to <strong>${fmt(vc.constrained_amount)}</strong></p>`;
    if (vc.scenarios?.length) {
      const keys = Object.keys(vc.scenarios[0]).filter(k => !k.startsWith('_'));
      vcHtml += makeTable(
        keys.map(k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())),
        vc.scenarios.map(s => keys.map(k => s[k]))
      );
    }
  }
  const finHtml = s3.significant_financing_component
    ? `<div class="inline-warning">⚠ Significant financing component may exist — max payment gap
       ${Math.round(s3.max_payment_gap_months)} months (exceeds 12-month expedient, ASC 606-10-32-18).</div>`
    : `<p class="caption">No significant financing component (max payment gap: ${Math.round(s3.max_payment_gap_months)} months).</p>`;

  return `
    <div class="metrics-grid metrics-grid-3">
      <div class="metric-card">
        <div class="metric-label">Fixed Consideration</div>
        <div class="metric-value">${fmt(s3.fixed_consideration)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Variable (constrained)</div>
        <div class="metric-value">${vc ? fmt(vc.constrained_amount) : '—'}</div>
      </div>
      <div class="metric-card metric-card--hero">
        <div class="metric-label">Transaction Price</div>
        <div class="metric-value">${fmt(s3.transaction_price)}</div>
      </div>
    </div>
    ${vcHtml}${finHtml}
  `;
}

function bodyStep4(s4) {
  const methodLabel = s4.method === 'relative_ssp' ? 'Relative SSP' : 'Residual';
  const totalAlloc  = s4.allocations.reduce((sum, a) => sum + (a.allocated_value || 0), 0);
  const rows = [
    ...s4.allocations.map(a => [
      a.name,
      a.ssp ? fmt(a.ssp) : 'Residual',
      SSP_LABELS[a.ssp_source] || a.ssp_source || '—',
      a.ssp_pct ? `${a.ssp_pct.toFixed(1)}%` : '—',
      fmt(a.allocated_value),
    ]),
    ['Total', '', '', s4.method === 'relative_ssp' ? '100%' : '—', fmt(totalAlloc)],
  ];
  return `
    <div class="metrics-grid metrics-grid-3" style="margin-bottom:12px">
      <div class="metric-card">
        <div class="metric-label">Method</div>
        <div class="metric-value metric-value-sm">${methodLabel}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Total SSP</div>
        <div class="metric-value">${s4.total_ssp ? fmt(s4.total_ssp) : 'N/A'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Discount</div>
        <div class="metric-value">${s4.discount ? fmt(Math.abs(s4.discount)) : '$0.00'}</div>
      </div>
    </div>
    ${makeTable(['Obligation', 'SSP', 'SSP Basis', 'SSP %', 'Allocated'], rows, rows.length - 1)}
  `;
}

function bodyStep5(s5, result) {
  const rows = s5.recognition_summary.map(r => {
    let desc;
    if (r.pattern === 'over_time')
      desc = `${fmt(r.monthly_amount)}/month × ${r.periods} months`;
    else if (r.pattern === 'point_in_time' || r.pattern === 'upfront')
      desc = `${fmt(r.amount)} on ${r.completion_date || 'Day 1'}`;
    else
      desc = `~${fmt(r.estimated_monthly)}/month (estimated)`;
    return [r.name, REC_LABELS[r.pattern] || r.pattern, desc,
            fmt(r.total || r.amount || r.total_constrained || 0)];
  });
  return makeTable(['Obligation', 'Pattern', 'Schedule', 'Total'], rows);
}

// ── Step conclusions ──────────────────────────────────────────────────────────

function stepConclusions(step_data, result) {
  const s1 = step_data.step_1;
  const s2 = step_data.step_2;
  const s3 = step_data.step_3;
  const s4 = step_data.step_4;
  const s5 = step_data.step_5;

  const oblNames = s2.obligations.map(o => o.name);
  const oblText  = oblNames.length <= 2
    ? oblNames.join(' & ')
    : `${oblNames[0]} + ${oblNames.length - 1} more`;

  const totalAlloc = s4.allocations.reduce((sum, a) => sum + (a.allocated_value || 0), 0);

  const patterns = [...new Set(s5.recognition_summary.map(r => REC_LABELS[r.pattern] || r.pattern))];
  const recDesc  = s5.recognition_summary.length === 1
    ? (() => {
        const r = s5.recognition_summary[0];
        if (r.pattern === 'over_time') return `${fmt(r.monthly_amount)}/month straight-line`;
        if (r.pattern === 'upfront')   return `${fmt(r.amount)} on day 1`;
        return patterns.join(' & ');
      })()
    : patterns.join(' & ');

  return {
    1: `${s1.contract_id} — ${fmtShort(s1.total_contract_value)}, ${s1.duration_months} months`,
    2: `${s2.obligations.length} obligation${s2.obligations.length !== 1 ? 's' : ''} — ${oblText}`,
    3: `${fmt(s3.transaction_price)}${s3.variable_consideration ? ' (includes variable consideration)' : ', fixed price'}`,
    4: `${s4.method === 'relative_ssp' ? 'Relative SSP' : 'Residual'} — ${fmt(totalAlloc)} allocated`,
    5: recDesc,
  };
}

// ── Snapshot ──────────────────────────────────────────────────────────────────

function snapshotCalc(schedule, asOf) {
  const past = schedule.filter(r => r.period_end <= asOf);
  if (!past.length) return { rev_to_date: 0, deferred: 0, contract_asset: 0, periods_complete: 0 };
  const last = past[past.length - 1];
  return {
    rev_to_date: last.cumulative_revenue, deferred: last.contract_liability,
    contract_asset: last.contract_asset, periods_complete: past.length,
  };
}

// ── Charts ────────────────────────────────────────────────────────────────────

const CHART_LAYOUT = {
  height: 300,
  margin: { l: 60, r: 12, t: 12, b: 80 },
  legend: { orientation: 'h', yanchor: 'top', y: -0.22, xanchor: 'center', x: 0.5 },
  showlegend: true,
  font: { family: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', size: 12, color: '#697386' },
  plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff',
};

function asOfMarker(schedule, asOf) {
  const past = schedule.filter(r => r.period_end <= asOf);
  if (!past.length) return { shapes: [], annotations: [] };
  const x = past[past.length - 1].period;
  return {
    shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0: x, x1: x, y0: 0, y1: 1,
               line: { dash: 'dash', color: '#9ca3af', width: 1 } }],
    annotations: [{ xref: 'x', yref: 'paper', x, y: 0.97, text: 'Today',
                    showarrow: false, xanchor: 'right', font: { color: '#9ca3af', size: 11 } }],
  };
}

function renderRevenueChart(result, asOf) {
  const el = document.getElementById('revenue-chart');
  if (!el) return;
  const { schedule, obligations } = result;
  const periods = schedule.map(r => r.period);
  const traces  = obligations.map(ob => ({
    name: ob.name, x: periods,
    y: schedule.map(r => r[`rev_${ob.id}`] || 0), type: 'bar',
  }));
  const { shapes, annotations } = asOfMarker(schedule, asOf);
  Plotly.newPlot(el, traces, {
    ...CHART_LAYOUT, barmode: 'stack', shapes, annotations,
    yaxis: { tickformat: '$,.0f', title: 'Revenue ($)', gridcolor: '#f0f0f0' },
    xaxis: { tickangle: -45 },
  }, { responsive: true, displayModeBar: false });
}

function renderBalanceChart(result, asOf) {
  const el = document.getElementById('balance-chart');
  if (!el) return;
  const { schedule } = result;
  const { shapes, annotations } = asOfMarker(schedule, asOf);
  Plotly.newPlot(el, [
    { name: 'Deferred Revenue', x: schedule.map(r => r.period), y: schedule.map(r => r.contract_liability),
      mode: 'lines+markers', fill: 'tozeroy', line: { color: '#ef4444', width: 2 }, marker: { size: 4 } },
    { name: 'Unbilled Revenue', x: schedule.map(r => r.period), y: schedule.map(r => r.contract_asset),
      mode: 'lines+markers', fill: 'tozeroy', line: { color: '#10b981', width: 2 }, marker: { size: 4 } },
  ], {
    ...CHART_LAYOUT, hovermode: 'x unified', shapes, annotations,
    yaxis: { tickformat: '$,.0f', gridcolor: '#f0f0f0' },
    xaxis: { tickangle: -45 },
  }, { responsive: true, displayModeBar: false });
}

// ── Journal entries ───────────────────────────────────────────────────────────

function renderJournalEntries(schedule, obligations) {
  return schedule
    .filter(r => (r.revenue_total || 0) > 0 || (r.billings || 0) > 0)
    .map(row => {
      const label   = `${row.period} &nbsp;·&nbsp; Revenue ${fmt(row.revenue_total || 0)}`
                    + (row.billings > 0 ? ` &nbsp;·&nbsp; Billed ${fmt(row.billings)}` : '');
      const entries = journalEntries(row, obligations);
      return `<details class="je-period">
        <summary>${label}</summary>
        <div>${makeTable(['Account', 'Debit', 'Credit'], entries.map(e => [e.Account, e.Debit, e.Credit]))}</div>
      </details>`;
    }).join('');
}

function journalEntries(row, obligations) {
  const entries  = [];
  const revenue  = row.revenue_total || 0;
  const billings = row.billings || 0;
  if (billings > 0) {
    entries.push({ Account: 'Accounts Receivable',                  Debit: fmt(billings), Credit: '' });
    entries.push({ Account: 'Contract Liability (Deferred Revenue)', Debit: '',            Credit: fmt(billings) });
  }
  if (revenue > 0) {
    if (obligations.length > 1) {
      for (const ob of obligations) {
        const obRev = row[`rev_${ob.id}`] || 0;
        if (obRev > 0) {
          entries.push({ Account: `Contract Liability — ${ob.name}`, Debit: fmt(obRev), Credit: '' });
          entries.push({ Account: `Revenue — ${ob.name}`,            Debit: '',          Credit: fmt(obRev) });
        }
      }
    } else {
      const name = obligations[0]?.name || 'Revenue';
      entries.push({ Account: 'Contract Liability (Deferred Revenue)', Debit: fmt(revenue), Credit: '' });
      entries.push({ Account: `Revenue — ${name}`,                     Debit: '',            Credit: fmt(revenue) });
    }
  }
  return entries;
}

// ── SSE reasoning stream ──────────────────────────────────────────────────────

async function streamReasoning(contract, step_data) {
  try {
    const resp    = await fetch('/api/reasoning', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contract, step_data }),
    });
    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop();
      for (const chunk of chunks) {
        const line = chunk.trim();
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') return;
        try {
          const { step, text, error } = JSON.parse(payload);
          if (error) { console.error('Reasoning error:', error); return; }
          if (step && text) showAIBadge(step, text);
        } catch { /* ignore */ }
      }
    }
  } catch (e) { console.error('SSE stream failed:', e); }
}

function showAIBadge(stepKey, data) {
  const badge = document.getElementById(`ai-${stepKey}`);
  if (badge) {
    badge.classList.remove('ai-badge--loading');
    if (typeof data === 'string') {
      badge.innerHTML = data;
    } else {
      const points = (data.reasoning || []).map(p => `<li>${p}</li>`).join('');
      badge.innerHTML = `
        ${data.finding ? `<div class="ai-finding">${data.finding}</div>` : ''}
        ${points ? `<ul class="ai-points">${points}</ul>` : ''}
        ${data.citation ? `<span class="ai-citation">${data.citation}</span>` : ''}
      `;
    }
  }

  const num    = stepKey.replace('step_', '');
  const status = document.getElementById(`step-ai-status-${num}`);
  if (status) status.innerHTML = `<span class="step-ai-check">✓</span>`;

  const navStatus = document.getElementById(`nav-status-${num}`);
  if (navStatus) { navStatus.classList.remove('spin'); navStatus.classList.add('done'); navStatus.textContent = '✓'; }
}

// ── Download CSV ──────────────────────────────────────────────────────────────

function downloadCSV() {
  if (!_currentData) return;
  const { result } = _currentData;
  const { schedule, summary } = result;
  if (!schedule.length) return;
  const headers = Object.keys(schedule[0]);
  const csv     = [headers.join(','), ...schedule.map(r => headers.map(h => r[h] ?? '').join(','))].join('\n');
  const a       = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(new Blob([csv], { type: 'text/csv' })),
    download: `${summary.contract_id}_schedule.csv`,
  });
  a.click(); URL.revokeObjectURL(a.href);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v) {
  const n = parseFloat(v);
  if (isNaN(n)) return String(v ?? '');
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtShort(v) {
  const n = parseFloat(v);
  if (isNaN(n)) return String(v ?? '');
  if (n >= 1_000_000) return '$' + (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1_000)     return '$' + Math.round(n / 1_000) + 'K';
  return fmt(v);
}

function fmtDateRange(start, end) {
  if (!start || !end) return '';
  const s = new Date(start + 'T00:00:00');
  const e = new Date(end   + 'T00:00:00');
  const crossYear = s.getFullYear() !== e.getFullYear();
  const sStr = s.toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(crossYear ? { year: 'numeric' } : {}) });
  const eStr = e.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return `${sStr} – ${eStr}`;
}

function todayStr() { return new Date().toISOString().slice(0, 10); }

function makeTable(headers, rows, totalRowIdx = -1) {
  const th = headers.map(h => `<th>${h}</th>`).join('');
  const tr = rows.map((row, i) => {
    const cls = i === totalRowIdx ? ' class="total-row"' : '';
    return `<tr${cls}>${row.map(cell => `<td>${cell ?? ''}</td>`).join('')}</tr>`;
  }).join('');
  return `<div class="table-wrap"><table class="data-table">
    <thead><tr>${th}</tr></thead><tbody>${tr}</tbody>
  </table></div>`;
}
