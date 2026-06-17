'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let menuItems = [];
let currentOrder = {};      // { item_id: qty }
let grillState = null;
let ws = null;
let config = {};
let orders = [];
let activeCommandesTab = 'en_preparation';
let countdownTimer = null;

const DRAFT_KEY = 'openkds_draft_v1';
const GRILL_COLLAPSED_KEY = 'openkds_grill_collapsed_v1';

// ── Router ────────────────────────────────────────────────────────────────────
// Each known path maps to a screen ID. Unknown paths fall back to cashier.
const ROUTES = {
  '/':         'cashier',
  '/orders':   'orders',
  '/stats':    'stats',
  '/settings': 'settings',
  '/grill':    'grill',
};

function navigate(path, replace = false) {
  const target = ROUTES[path] ? path : '/';
  if (location.pathname !== target) {
    if (replace) history.replaceState({}, '', target);
    else         history.pushState({}, '', target);
  }
  renderRoute(target);
  closeMenu();
}

function renderRoute(path) {
  const screenName = ROUTES[path] || 'cashier';
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const el = document.getElementById('screen-' + screenName);
  if (el) el.classList.add('active');

  document.querySelectorAll('.nav-btn[data-link]').forEach(a => {
    const href = a.getAttribute('href');
    a.classList.toggle('active', href === path);
  });

  // Per-screen load hooks
  if (screenName === 'stats')    loadStats();
  if (screenName === 'settings') loadSettings();
  if (screenName === 'grill')    renderGrillFull();
  if (screenName === 'orders')   refreshCommandesScreen();
}

function setupLinkInterceptor() {
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-link]');
    if (!a) return;
    const href = a.getAttribute('href');
    if (!href || !href.startsWith('/')) return;
    e.preventDefault();
    navigate(href);
  });
  window.addEventListener('popstate', () => renderRoute(location.pathname));
}

// Backwards-compat helper for inline onclick="showScreen('xxx')" calls.
function showScreen(name) {
  const path = Object.entries(ROUTES).find(([, n]) => n === name)?.[0] || '/';
  navigate(path);
}

// ── Mobile menu drawer ────────────────────────────────────────────────────────
function toggleMenu() {
  const open = document.body.classList.toggle('menu-open');
  document.getElementById('menu-backdrop').style.display = open ? 'block' : 'none';
}
function closeMenu() {
  document.body.classList.remove('menu-open');
  const backdrop = document.getElementById('menu-backdrop');
  if (backdrop) backdrop.style.display = 'none';
}

// ── Grill widget accordion ────────────────────────────────────────────────────
function toggleGrillWidget() {
  const w = document.getElementById('grill-widget');
  if (!w) return;
  const collapsed = w.classList.toggle('collapsed');
  const toggle = w.querySelector('.grill-widget-toggle');
  if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  try { localStorage.setItem(GRILL_COLLAPSED_KEY, collapsed ? '1' : '0'); } catch {}
}

function applyGrillWidgetState() {
  const w = document.getElementById('grill-widget');
  if (!w) return;
  let collapsed = false;
  try { collapsed = localStorage.getItem(GRILL_COLLAPSED_KEY) === '1'; } catch {}
  w.classList.toggle('collapsed', collapsed);
  const toggle = w.querySelector('.grill-widget-toggle');
  if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  const params = new URLSearchParams(location.search);
  if (params.get('mode') === 'delivery') {
    document.body.classList.add('mode-delivery');
  }

  setupLinkInterceptor();
  applyGrillWidgetState();

  await Promise.all([loadConfig(), loadMenu()]);
  connectWebSocket();
  loadGrillState();
  loadOrders();
  refreshDraftBanner();

  // Initial render: derive screen from URL, or force orders in delivery mode.
  if (document.body.classList.contains('mode-delivery')) {
    navigate('/orders', /*replace=*/true);
  } else {
    renderRoute(location.pathname);
  }
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    config = await res.json();
    const parts = [config.org_name, config.event_name].filter(Boolean);
    document.getElementById('event-name').textContent = parts.join(' — ');
  } catch {}
}

async function loadMenu() {
  try {
    const res = await fetch('/api/menu');
    menuItems = await res.json();
    renderMenuButtons();
  } catch {}
}

async function loadOrders() {
  try {
    const res = await fetch('/api/orders');
    orders = await res.json();
    refreshCommandesScreen();
    refreshNavBadge();
  } catch {}
}

// ── Menu buttons ──────────────────────────────────────────────────────────────
function renderMenuButtons() {
  const panel = document.getElementById('menu-panel');
  panel.innerHTML = '';
  menuItems.forEach(item => {
    const btn = document.createElement('button');
    btn.className = 'menu-btn';
    btn.id = 'menu-btn-' + item.id;
    btn.style.background = item.color || '#555';
    btn.setAttribute('data-id', item.id);
    const label = document.createElement('span');
    label.className = 'btn-label';
    label.textContent = item.label;
    const badge = document.createElement('span');
    badge.className = 'qty-badge';
    badge.style.display = 'none';
    btn.appendChild(label);
    btn.appendChild(badge);
    btn.addEventListener('click', () => addItem(item.id));
    panel.appendChild(btn);
  });
}

function addItem(itemId) {
  currentOrder[itemId] = (currentOrder[itemId] || 0) + 1;
  updateOrderUI();
}

function updateOrderUI() {
  menuItems.forEach(item => {
    const badge = document.querySelector(`#menu-btn-${item.id} .qty-badge`);
    if (!badge) return;
    const qty = currentOrder[item.id] || 0;
    badge.textContent = qty;
    badge.style.display = qty > 0 ? 'inline-block' : 'none';
  });

  const lines = document.getElementById('order-lines');
  const items = menuItems.filter(i => (currentOrder[i.id] || 0) > 0);
  if (items.length === 0) {
    lines.innerHTML = '<p class="empty-msg">Aucun article</p>';
  } else {
    lines.innerHTML = items.map(item => {
      const qty = currentOrder[item.id];
      const shortLabel = item.label.replace('\n', ' ');
      return `<div class="order-line"><span><span class="qty">${qty}x</span>${shortLabel}</span></div>`;
    }).join('');
  }

  const total = Object.values(currentOrder).reduce((s, v) => s + v, 0);
  document.getElementById('btn-validate').disabled = total === 0;
  document.getElementById('btn-hold').disabled = total === 0;
}

// ── Submit order ───────────────────────────────────────────────────────────────
async function submitOrder() {
  const btn = document.getElementById('btn-validate');
  btn.disabled = true;

  const body = { items: {} };
  menuItems.forEach(i => { body.items[i.id] = currentOrder[i.id] || 0; });

  try {
    const res = await fetch('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    const num = String(data.number).padStart(3, '0');
    if (res.status === 200) {
      showToast(`✓ Commande #${num} imprimée`, 'ok');
    } else if (res.status === 207) {
      const errs = Object.entries(data)
        .filter(([k, v]) => k.endsWith('_status') && v !== 'ok')
        .map(([k, v]) => `${k.replace('_status','')}: ${v}`);
      showToast(`⚠️ Commande #${num} enregistrée — ${errs.join(' / ')}`, 'warn', 6000);
    } else {
      showToast(`Erreur: ${data.detail || 'inconnue'}`, 'err');
    }
    currentOrder = {};
    updateOrderUI();
  } catch {
    showToast('Erreur réseau', 'err');
    btn.disabled = false;
  }
}

// ── Cancel current draft ──────────────────────────────────────────────────────
function confirmCancel() {
  if (Object.values(currentOrder).reduce((s, v) => s + v, 0) === 0) return;
  showModal('cancel');
}

function cancelOrder() {
  currentOrder = {};
  updateOrderUI();
  closeModal();
}

// ── Hold / resume draft (localStorage) ────────────────────────────────────────
function holdOrder() {
  const total = Object.values(currentOrder).reduce((s, v) => s + v, 0);
  if (total === 0) return;
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(currentOrder));
  } catch {
    showToast('Impossible de sauvegarder en attente', 'err');
    return;
  }
  currentOrder = {};
  updateOrderUI();
  refreshDraftBanner();
  showToast('Commande mise en attente', 'ok');
}

function resumeDraft() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch {}
  if (!saved) return;
  currentOrder = saved;
  localStorage.removeItem(DRAFT_KEY);
  updateOrderUI();
  refreshDraftBanner();
  navigate('/');
}

function discardDraft() {
  localStorage.removeItem(DRAFT_KEY);
  refreshDraftBanner();
  showToast('Commande en attente supprimée', 'ok');
}

function refreshDraftBanner() {
  const banner = document.getElementById('draft-banner');
  if (!banner) return;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch {}
  if (!saved) {
    banner.style.display = 'none';
    return;
  }
  const labelById = Object.fromEntries(menuItems.map(i => [i.id, i.label.replace('\n', ' ')]));
  const summary = Object.entries(saved)
    .filter(([, q]) => q > 0)
    .map(([id, q]) => `${q}× ${labelById[id] || id}`)
    .join(', ');
  document.getElementById('draft-banner-summary').textContent =
    summary ? `— ${summary}` : '';
  banner.style.display = 'flex';
}

// ── WebSocket ──────────────────────────────────────────────────────────────────
function connectWebSocket() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => setWsStatus(true);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'order_created') {
      if (msg.order) mergeOrder(msg.order);
      if (msg.grill) updateGrill(msg.grill);
    } else if (msg.type === 'order_status_changed') {
      if (msg.order) mergeOrder(msg.order);
    } else if (msg.type === 'grill_updated') {
      if (msg.grill) updateGrill(msg.grill);
    } else if (msg.type === 'printer_error') {
      showToast(`⚠️ ${msg.message}`, 'err', 6000);
    }
  };
  ws.onclose = () => { setWsStatus(false); setTimeout(connectWebSocket, 3000); };
  ws.onerror = () => setWsStatus(false);
}

function setWsStatus(connected) {
  const dot = document.getElementById('ws-indicator');
  dot.className = 'ws-dot ' + (connected ? 'connected' : 'disconnected');
}

function mergeOrder(order) {
  const idx = orders.findIndex(o => o.id === order.id);
  if (idx >= 0) orders[idx] = order;
  else orders.unshift(order);
  refreshCommandesScreen();
  refreshNavBadge();
}

function updateGrill(g) {
  grillState = g;
  renderGrillWidget();
  if (document.getElementById('screen-grill').classList.contains('active')) {
    renderGrillFull();
  }
}

// ── Grill helpers ──────────────────────────────────────────────────────────────
function firstDashboard() {
  if (!grillState?.dashboards) return null;
  const keys = Object.keys(grillState.dashboards);
  return keys.length ? grillState.dashboards[keys[0]] : null;
}

async function loadGrillState() {
  try {
    const res = await fetch('/api/grill');
    grillState = await res.json();
    renderGrillWidget();
  } catch {}
}

function renderGrillWidget() {
  const container = document.getElementById('grill-widget-content');
  const dash = firstDashboard();
  if (!dash) {
    container.innerHTML = '<span style="color:#888;font-size:.8rem">Chargement…</span>';
    return;
  }
  const { tracks, track_labels, demand, gauges } = dash;
  container.innerHTML = tracks.map(tr => {
    const g = gauges?.[tr] ?? 0;
    const d = demand?.[tr] ?? 0;
    const segs = [1,2,3,4].map(i =>
      `<span class="mini-seg ${i <= g ? 'on-' + g : ''}"></span>`
    ).join('');
    const shortName = (track_labels?.[tr] || tr).substring(0, 6);
    return `<div class="grill-row">
      <span class="mini-gauge">${segs}</span>
      <span>${shortName}: <strong>${d}</strong></span>
    </div>`;
  }).join('');
}

function renderGrillFull() {
  const container = document.getElementById('grill-content');
  const dash = firstDashboard();
  if (!dash) {
    container.innerHTML = '<p style="padding:16px;color:#888">Chargement…</p>';
    loadGrillState();
    return;
  }
  const { tracks, track_labels, demand, gauges, stock, stock_buckets, window_minutes } = dash;
  const GAUGE_LABELS = ['Att.', '+½ doz.', '+1 doz.', '+2 doz.', 'Urgence!'];

  container.innerHTML = tracks.map(tr => {
    const d = demand?.[tr] ?? 0;
    const g = gauges?.[tr] ?? 0;
    const stockIdx = stock?.[tr] ?? 0;
    const label = track_labels?.[tr] || tr;
    const segments = [1,2,3,4].map(i =>
      `<div class="gauge-segment ${i <= g ? 'lit-' + g : ''}"></div>`
    ).join('');
    const segLabels = GAUGE_LABELS.map(l => `<div class="gauge-label">${l}</div>`).join('');
    const stockBtns = (stock_buckets || []).map((b, i) =>
      `<button class="stock-btn ${i === stockIdx ? 'active' : ''}"
        onclick="setStock('${tr}', ${i})">${b.label}</button>`
    ).join('');
    return `<div class="grill-meat-block">
      <div class="grill-meat-title">${label}</div>
      <div class="grill-demand-line">Demande (${window_minutes} min) : <strong>${d} pièces</strong></div>
      <div class="gauge-row">${segments}</div>
      <div class="gauge-labels">${segLabels}</div>
      <div class="stock-label">Stock réchaud :</div>
      <div class="stock-buttons">${stockBtns}</div>
    </div>`;
  }).join('');
}

async function setStock(component, bucketIndex) {
  try {
    const res = await fetch('/api/grill/stock', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [component]: bucketIndex }),
    });
    grillState = await res.json();
    renderGrillWidget();
    renderGrillFull();
  } catch {
    showToast('Erreur mise à jour stock', 'err');
  }
}

// ── Commandes screen ──────────────────────────────────────────────────────────
function showCommandesTab(status) {
  activeCommandesTab = status;
  document.querySelectorAll('.cmd-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === status);
  });
  refreshCommandesScreen();
}

function refreshCommandesScreen() {
  const counts = { en_preparation: 0, livre: 0, annule: 0 };
  for (const o of orders) counts[o.status] = (counts[o.status] || 0) + 1;
  for (const status of Object.keys(counts)) {
    const el = document.getElementById(`cmd-tab-${status}-count`);
    if (el) el.textContent = counts[status];
  }

  const filtered = orders
    .filter(o => o.status === activeCommandesTab)
    .sort((a, b) => activeCommandesTab === 'en_preparation'
      ? a.number - b.number
      : b.number - a.number);

  const list = document.getElementById('commandes-list');
  if (filtered.length === 0) {
    list.innerHTML = '<p class="empty-msg">Aucune commande</p>';
    return;
  }
  const labelById = Object.fromEntries(menuItems.map(i => [i.id, i.label.replace('\n', ' ')]));
  list.innerHTML = filtered.map(o => renderOrderCard(o, labelById)).join('');

  startCountdownLoop();
  // Sync update so progress bars render at the correct fill immediately,
  // instead of starting at the CSS default (0%) and waiting one second.
  updateCountdowns();
}

function renderOrderCard(o, labelById) {
  const num = String(o.number).padStart(3, '0');
  const time = (o.created_at || '').substring(11, 16);
  const items = o.items || {};
  const itemsHtml = Object.entries(items)
    .filter(([, q]) => q > 0)
    .map(([id, q]) => `<li><span class="qty">${q}×</span>${labelById[id] || id}</li>`)
    .join('');

  // Use the server-provided epoch timestamps for time math; never re-parse
  // the display string, which would mismatch when the server timezone
  // differs from the browser's (e.g. UTC container vs. local browser).
  const createdTs = (o.created_at_ts || 0) * 1000;
  const targetTs  = (o.auto_delivery_at || 0) * 1000;
  const showCountdown = o.status === 'en_preparation' && targetTs > 0 && createdTs > 0;

  const countdownHtml = showCountdown ? `
    <div class="cmd-progress"><div class="cmd-progress-bar"
      data-created="${createdTs}"
      data-target="${targetTs}"></div></div>
    <div class="cmd-countdown" data-target="${targetTs}">…</div>` : '';

  let actions;
  if (o.status === 'en_preparation') {
    const delaysRow = showCountdown ? `
      <div class="cmd-delays">
        <button class="btn-delay" onclick="delayOrder(${o.id},60)">+1 min</button>
        <button class="btn-delay" onclick="delayOrder(${o.id},150)">+2½ min</button>
        <button class="btn-delay" onclick="delayOrder(${o.id},300)">+5 min</button>
      </div>` : '';
    actions = `${delaysRow}
      <div class="cmd-actions">
        <button class="btn-deliver" onclick="deliverOrder(${o.id})">Livrer</button>
        <button class="btn-reprint-mini" onclick="reprintOrder(${o.id}, this)">🖨</button>
        <button class="btn-cancel-order" onclick="confirmCancelOrder(${o.id}, ${o.number})">Annuler</button>
      </div>`;
  } else {
    actions = `<div class="cmd-actions">
      <button class="btn-reprint-mini" onclick="reprintOrder(${o.id}, this)">🖨 Réimprimer</button>
    </div>`;
  }

  return `<div class="cmd-card status-${o.status}" id="cmd-card-${o.id}">
    <div class="cmd-head">
      <span class="cmd-num">#${num}</span>
      <span class="cmd-time">${time}</span>
    </div>
    <ul class="cmd-items">${itemsHtml}</ul>
    ${countdownHtml}
    ${actions}
  </div>`;
}

function startCountdownLoop() {
  if (countdownTimer) return;
  countdownTimer = setInterval(updateCountdowns, 1000);
}

function stopCountdownLoop() {
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}

function updateCountdowns() {
  const bars = document.querySelectorAll('.cmd-progress-bar[data-target]');
  if (bars.length === 0) { stopCountdownLoop(); return; }
  const now = Date.now();
  bars.forEach(bar => {
    const created = Number(bar.dataset.created);
    const target = Number(bar.dataset.target);
    if (!created || !target) return;
    const total = target - created;
    if (total <= 0) return;
    const elapsed = now - created;
    const pct = Math.max(0, Math.min(100, (elapsed / total) * 100));
    bar.style.width = pct + '%';
    const card = bar.closest('.cmd-card');
    if (card) {
      card.classList.toggle('overdue', now > target);
      card.classList.toggle('imminent', !card.classList.contains('overdue') && pct >= 80);
    }
  });
  document.querySelectorAll('.cmd-countdown[data-target]').forEach(el => {
    const target = Number(el.dataset.target);
    const diff = target - now;
    if (diff <= 0) {
      el.textContent = 'Livraison auto imminente';
    } else {
      const mins = Math.floor(diff / 60000);
      const secs = Math.floor((diff % 60000) / 1000);
      el.textContent = `Auto dans ${mins}:${String(secs).padStart(2, '0')}`;
    }
  });
}

function refreshNavBadge() {
  const badge = document.getElementById('cmd-nav-badge');
  if (!badge) return;
  const n = orders.filter(o => o.status === 'en_preparation').length;
  badge.textContent = n;
  badge.style.display = n > 0 ? 'inline-block' : 'none';
}

// ── Order actions ─────────────────────────────────────────────────────────────
async function deliverOrder(id) { await patchStatus(id, 'livre'); }

async function patchStatus(id, status) {
  try {
    const res = await fetch(`/api/orders/${id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error();
  } catch {
    showToast('Erreur mise à jour statut', 'err');
  }
}

async function delayOrder(id, seconds) {
  try {
    const res = await fetch(`/api/orders/${id}/delay`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ additional_seconds: seconds }),
    });
    if (!res.ok) throw new Error();
  } catch {
    showToast('Erreur ajustement délai', 'err');
  }
}

let _pendingCancelOrderId = null;
function confirmCancelOrder(id, number) {
  _pendingCancelOrderId = id;
  document.getElementById('modal-cancel-order-number').textContent =
    '#' + String(number).padStart(3, '0');
  document.getElementById('modal-cancel-order-confirm').onclick = async () => {
    closeModal();
    if (_pendingCancelOrderId) {
      await patchStatus(_pendingCancelOrderId, 'annule');
      _pendingCancelOrderId = null;
    }
  };
  showModal('cancel-order');
}

// ── Reprint ────────────────────────────────────────────────────────────────────
async function reprintOrder(orderId, btn) {
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '…';
  try {
    const res = await fetch(`/api/orders/${orderId}/reprint`, { method: 'POST' });
    const data = await res.json();
    const ok = Object.values(data).every(v => v === 'ok');
    btn.textContent = ok ? '✓' : '⚠️';
    setTimeout(() => {
      btn.textContent = originalText;
      btn.disabled = false;
    }, 3000);
  } catch {
    btn.textContent = '⚠️';
    btn.disabled = false;
  }
}

// ── Stats ──────────────────────────────────────────────────────────────────────
async function loadStats() {
  const container = document.getElementById('stats-content');
  container.innerHTML = '<p style="color:#888;padding:8px">Chargement…</p>';
  try {
    const res = await fetch('/api/stats');
    const stats = await res.json();

    const menuRows = (stats.items || []).map(i =>
      `<tr><td>${i.label}</td><td>${i.total}</td></tr>`
    ).join('');
    const compRows = Object.entries(stats.components || {}).map(([k, v]) =>
      `<tr><td>${k}</td><td>${v}</td></tr>`
    ).join('');

    const sc = stats.status_counts || {};
    const statusBlock = `
      <div class="stats-card">
        <h2>Par statut</h2>
        <table class="stats-table">
          <tr><th>Statut</th><th>Nombre</th></tr>
          <tr><td>En préparation</td><td>${sc.en_preparation || 0}</td></tr>
          <tr><td>Livrées</td><td>${sc.livre || 0}</td></tr>
          <tr><td>Annulées</td><td>${sc.annule || 0}</td></tr>
        </table>
      </div>`;

    const histo = stats.histogram || [];
    let histoHtml = '<p style="color:#888;font-size:.85rem">Aucune donnée</p>';
    if (histo.length > 0) {
      const maxCount = Math.max(...histo.map(h => h.count), 1);
      const bars = histo.map(h => {
        const pct = Math.round((h.count / maxCount) * 100);
        return `<div class="histo-bar" style="height:${pct}%">
          <span class="histo-bar-label">${h.slot}</span>
        </div>`;
      }).join('');
      histoHtml = `<div class="histogram-wrap"><div class="histogram">${bars}</div></div>`;
    }

    container.innerHTML = `
      <div class="stats-card">
        <h2>Total commandes</h2>
        <div class="stats-total">${stats.total_orders}</div>
      </div>
      ${statusBlock}
      <div class="stats-card">
        <h2>Par article (hors annulées)</h2>
        <table class="stats-table">
          <tr><th>Article</th><th>Quantité</th></tr>
          ${menuRows}
        </table>
      </div>
      <div class="stats-card">
        <h2>Composants (hors annulées)</h2>
        <table class="stats-table">
          <tr><th>Composant</th><th>Total</th></tr>
          ${compRows}
        </table>
      </div>
      <div class="stats-card">
        <h2>Activité (tranches de 10 min)</h2>
        ${histoHtml}
      </div>`;
  } catch {
    container.innerHTML = '<p style="color:#e74c3c;padding:8px">Erreur de chargement</p>';
  }
}

// ── Settings ───────────────────────────────────────────────────────────────────
async function loadSettings() {
  try {
    const [cfgRes, statsRes, printersRes] = await Promise.all([
      fetch('/api/config'),
      fetch('/api/stats'),
      fetch('/api/printers'),
    ]);
    config = await cfgRes.json();
    const stats = await statsRes.json();
    const printers = await printersRes.json();

    document.getElementById('warning-service').style.display =
      stats.total_orders > 0 ? 'block' : 'none';

    document.getElementById('printer-settings-list').innerHTML = printers.map((p, i) => {
      const s = p.status || {};
      const badgeClass = s.connected ? (s.paper_ok ? 'ok' : 'err') : 'err';
      const badgeText = s.connected ? (s.paper_ok ? '✓ OK' : '⚠️ Papier') : '✗ Déconnectée';
      return `<div class="printer-card"${i > 0 ? ' style="margin-top:12px"' : ''}>
        <strong>${p.label || p.id}</strong>
        <span class="printer-badge ${badgeClass}">${badgeText}</span>
        <button onclick="testPrinter('${p.id}')" class="btn-test">Test</button>
      </div>
      <div class="printer-device-row">
        <label>Périphérique :
          <input type="text" id="input-printer-device-${p.id}" class="input-field"
                 style="width:180px" placeholder="/dev/ttyACM0 ou 04b8:0e15"
                 value="${p.device || ''}">
        </label>
      </div>`;
    }).join('');

    document.getElementById('input-grill-window').value = config.grill_window_minutes;
    document.getElementById('input-grill-segment').value = config.grill_segment_size;
    document.getElementById('input-grill-threshold').value = config.grill_demand_threshold ?? 3;
    document.getElementById('input-org-name').value = config.org_name || '';
    document.getElementById('input-event-name').value = config.event_name || '';
    document.getElementById('input-next-order').value = config.next_order_number;
    document.getElementById('input-auto-delivery-enabled').checked = !!config.auto_delivery_enabled;
    document.getElementById('input-auto-delivery-minutes').value = config.auto_delivery_minutes ?? 20;

    const pickersDiv = document.getElementById('color-pickers');
    pickersDiv.innerHTML = menuItems.map(item =>
      `<div class="color-row">
        <input type="color" id="color-${item.id}" value="${config.button_colors?.[item.id] || item.color || '#888888'}">
        <label for="color-${item.id}">${item.label.replace('\n', ' ')}</label>
      </div>`
    ).join('');
  } catch {}
}

async function saveIdentity() {
  const org = document.getElementById('input-org-name').value.trim();
  const evt = document.getElementById('input-event-name').value.trim();
  await saveConfigFields({ org_name: org, event_name: evt });
  const parts = [org, evt].filter(Boolean);
  document.getElementById('event-name').textContent = parts.join(' — ');
  showToast('Identité enregistrée', 'ok');
}

async function savePrinterDevices() {
  const devices = {};
  document.querySelectorAll('[id^="input-printer-device-"]').forEach(el => {
    const id = el.id.replace('input-printer-device-', '');
    devices[id] = el.value.trim();
  });
  await saveConfigFields({ printer_devices: devices });
  showToast('Périphériques enregistrés', 'ok');
  await loadSettings();
}

async function saveNextOrder() {
  const val = parseInt(document.getElementById('input-next-order').value);
  if (isNaN(val) || val < 1) { showToast('Numéro invalide', 'err'); return; }
  await saveConfigFields({ next_order_number: val });
  showToast('Numéro enregistré', 'ok');
}

async function saveGrillParams() {
  const w = parseInt(document.getElementById('input-grill-window').value);
  const s = parseInt(document.getElementById('input-grill-segment').value);
  const th = parseInt(document.getElementById('input-grill-threshold').value);
  if (isNaN(w) || w < 1 || isNaN(s) || s < 1 || isNaN(th) || th < 0) {
    showToast('Valeurs invalides', 'err'); return;
  }
  await saveConfigFields({
    grill_window_minutes: w,
    grill_segment_size: s,
    grill_demand_threshold: th,
  });
  showToast('Paramètres enregistrés', 'ok');
}

async function saveAutoDelivery() {
  const enabled = document.getElementById('input-auto-delivery-enabled').checked;
  const minutes = parseFloat(document.getElementById('input-auto-delivery-minutes').value);
  if (isNaN(minutes) || minutes <= 0) {
    showToast('Délai invalide', 'err'); return;
  }
  await saveConfigFields({
    auto_delivery_enabled: enabled,
    auto_delivery_minutes: minutes,
  });
  showToast('Livraison auto enregistrée', 'ok');
  loadOrders();
}

async function saveColors() {
  const colors = {};
  menuItems.forEach(item => {
    const el = document.getElementById('color-' + item.id);
    if (el) colors[item.id] = el.value;
  });
  await saveConfigFields({ button_colors: colors });
  await loadMenu();
  showToast('Couleurs enregistrées', 'ok');
}

async function saveConfigFields(updates) {
  try {
    const res = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    config = await res.json();
  } catch {
    showToast('Erreur de sauvegarde', 'err');
  }
}

async function testPrinter(id) {
  try {
    const res = await fetch('/api/printers/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ printer: id }),
    });
    const data = await res.json();
    if (data[id] === 'ok') showToast(`${id} : test OK`, 'ok');
    else showToast(`${id} : ${data[id]}`, 'err');
  } catch {
    showToast('Erreur réseau', 'err');
  }
}

// ── Reset ──────────────────────────────────────────────────────────────────────
function confirmReset() { showModal('reset1'); }
function confirmReset2() { closeModal(); showModal('reset2'); }

async function doReset() {
  closeModal();
  try {
    const res = await fetch('/api/orders', {
      method: 'DELETE',
      headers: { 'X-Confirm-Reset': 'yes' },
    });
    if (res.ok) {
      showToast('Reset effectué', 'ok');
      currentOrder = {};
      updateOrderUI();
      orders = [];
      refreshCommandesScreen();
      refreshNavBadge();
      await loadConfig();
    } else {
      showToast('Erreur lors du reset', 'err');
    }
  } catch {
    showToast('Erreur réseau', 'err');
  }
}

// ── Modal helpers ──────────────────────────────────────────────────────────────
function showModal(name) {
  document.getElementById('modal-overlay').style.display = 'flex';
  document.getElementById('modal-' + name).style.display = 'block';
}

function closeModal() {
  document.getElementById('modal-overlay').style.display = 'none';
  document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
}

document.getElementById('modal-overlay').addEventListener('click', (e) => {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
});

// ── Toast ──────────────────────────────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type = 'ok', duration = 3500) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast ' + type;
  el.style.display = 'block';
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.style.display = 'none'; }, duration);
}

// ── Boot ───────────────────────────────────────────────────────────────────────
init();
