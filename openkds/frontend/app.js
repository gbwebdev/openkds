'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let menuItems = [];
let currentOrder = {};   // { item_id: qty }
let grillState = null;
let ws = null;
let config = {};

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  await Promise.all([loadConfig(), loadMenu()]);
  connectWebSocket();
  loadGrillState();
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

// ── Screen navigation ──────────────────────────────────────────────────────────
function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById('screen-' + name).classList.add('active');
  if (name === 'history') loadHistory();
  if (name === 'stats') loadStats();
  if (name === 'settings') loadSettings();
  if (name === 'grill') renderGrillFull();
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

// ── Cancel order ───────────────────────────────────────────────────────────────
function confirmCancel() {
  if (Object.values(currentOrder).reduce((s, v) => s + v, 0) === 0) return;
  showModal('cancel');
}

function cancelOrder() {
  currentOrder = {};
  updateOrderUI();
  closeModal();
}

// ── WebSocket ──────────────────────────────────────────────────────────────────
function connectWebSocket() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => setWsStatus(true);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'order_created' || msg.type === 'grill_updated') {
      if (msg.grill) {
        grillState = msg.grill;
        renderGrillWidget();
        if (document.getElementById('screen-grill').classList.contains('active')) {
          renderGrillFull();
        }
      }
    }
    if (msg.type === 'printer_error') {
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

// ── Grill widget (main screen) ─────────────────────────────────────────────────
function renderGrillWidget() {
  const container = document.getElementById('grill-widget-content');
  const dash = firstDashboard();
  if (!dash) {
    container.innerHTML = '<span style="color:#888;font-size:.8rem">Chargement…</span>';
    return;
  }

  const { tracks, track_labels, demand, gauges } = dash;
  container.innerHTML = tracks.map(t => {
    const g = gauges?.[t] ?? 0;
    const d = demand?.[t] ?? 0;
    const segs = [1,2,3,4].map(i =>
      `<span class="mini-seg ${i <= g ? 'on-' + g : ''}"></span>`
    ).join('');
    const shortName = (track_labels?.[t] || t).substring(0, 6);
    return `<div class="grill-row">
      <span class="mini-gauge">${segs}</span>
      <span>${shortName}: <strong>${d}</strong></span>
    </div>`;
  }).join('');
}

// ── Grill full screen ──────────────────────────────────────────────────────────
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

  container.innerHTML = tracks.map(t => {
    const d = demand?.[t] ?? 0;
    const g = gauges?.[t] ?? 0;
    const stockIdx = stock?.[t] ?? 0;
    const label = track_labels?.[t] || t;

    const segments = [1,2,3,4].map(i =>
      `<div class="gauge-segment ${i <= g ? 'lit-' + g : ''}"></div>`
    ).join('');
    const segLabels = GAUGE_LABELS.map(l => `<div class="gauge-label">${l}</div>`).join('');
    const stockBtns = (stock_buckets || []).map((b, i) =>
      `<button class="stock-btn ${i === stockIdx ? 'active' : ''}"
        onclick="setStock('${t}', ${i})">${b.label}</button>`
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

// ── History ────────────────────────────────────────────────────────────────────
async function loadHistory() {
  const list = document.getElementById('history-list');
  list.innerHTML = '<p style="color:#888;padding:8px">Chargement…</p>';
  try {
    const res = await fetch('/api/orders');
    const orders = await res.json();
    if (orders.length === 0) {
      list.innerHTML = '<p style="color:#888;padding:8px">Aucune commande</p>';
      return;
    }
    const itemLabelMap = Object.fromEntries(
      menuItems.map(i => [i.id, i.label.replace('\n', ' ')])
    );
    list.innerHTML = orders.map(o => {
      const num = String(o.number).padStart(3, '0');
      const time = o.created_at.substring(11, 16);
      const items = o.items || {};
      const parts = Object.entries(items)
        .filter(([, qty]) => qty > 0)
        .map(([id, qty]) => `${qty}x ${itemLabelMap[id] || id}`);
      return `<div class="history-item" id="hist-${o.id}">
        <div class="history-item-text">
          <span class="history-item-num">#${num}</span>
          <span class="history-item-time"> — ${time} — </span>
          ${parts.join(', ')}
        </div>
        <button class="btn-reprint" onclick="reprintOrder(${o.id}, this)">🖨 Réimprimer</button>
      </div>`;
    }).join('');
  } catch {
    list.innerHTML = '<p style="color:#e74c3c;padding:8px">Erreur de chargement</p>';
  }
}

async function reprintOrder(orderId, btn) {
  btn.disabled = true;
  btn.textContent = '…';
  try {
    const res = await fetch(`/api/orders/${orderId}/reprint`, { method: 'POST' });
    const data = await res.json();
    const ok = Object.values(data).every(v => v === 'ok');
    btn.textContent = ok ? '✓' : '⚠️';
    btn.className = 'btn-reprint ' + (ok ? 'ok' : 'err');
    setTimeout(() => {
      btn.textContent = '🖨 Réimprimer';
      btn.className = 'btn-reprint';
      btn.disabled = false;
    }, 3000);
  } catch {
    btn.textContent = '⚠️';
    btn.className = 'btn-reprint err';
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
      <div class="stats-card">
        <h2>Par article</h2>
        <table class="stats-table">
          <tr><th>Article</th><th>Quantité</th></tr>
          ${menuRows}
        </table>
      </div>
      <div class="stats-card">
        <h2>Composants</h2>
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
    const [cfgRes, statsRes, pRes] = await Promise.all([
      fetch('/api/config'),
      fetch('/api/stats'),
      fetch('/api/printers/status'),
    ]);
    config = await cfgRes.json();
    const stats = await statsRes.json();
    const printerStatus = await pRes.json();

    document.getElementById('warning-service').style.display =
      stats.total_orders > 0 ? 'block' : 'none';

    renderPrinterBadge('p1-status', printerStatus.printer1);
    renderPrinterBadge('p2-status', printerStatus.printer2);
    document.getElementById('input-printer1-device').value = config.printer1_device || '';
    document.getElementById('input-printer2-device').value = config.printer2_device || '';
    document.getElementById('input-grill-window').value = config.grill_window_minutes;
    document.getElementById('input-grill-segment').value = config.grill_segment_size;
    document.getElementById('input-org-name').value = config.org_name || '';
    document.getElementById('input-event-name').value = config.event_name || '';
    document.getElementById('input-next-order').value = config.next_order_number;

    // Color pickers — dynamic from current menuItems
    const pickersDiv = document.getElementById('color-pickers');
    pickersDiv.innerHTML = menuItems.map(item =>
      `<div class="color-row">
        <input type="color" id="color-${item.id}" value="${config.button_colors?.[item.id] || item.color || '#888888'}">
        <label for="color-${item.id}">${item.label.replace('\n', ' ')}</label>
      </div>`
    ).join('');
  } catch {}
}

function renderPrinterBadge(elemId, status) {
  const el = document.getElementById(elemId);
  if (!el || !status) return;
  if (status.connected) {
    el.textContent = status.paper_ok ? '✓ OK' : '⚠️ Papier';
    el.className = 'printer-badge ' + (status.paper_ok ? 'ok' : 'err');
  } else {
    el.textContent = '✗ Déconnectée';
    el.className = 'printer-badge err';
  }
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
  const d1 = document.getElementById('input-printer1-device').value.trim();
  const d2 = document.getElementById('input-printer2-device').value.trim();
  await saveConfigFields({ printer1_device: d1, printer2_device: d2 });
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
  if (isNaN(w) || w < 1 || isNaN(s) || s < 1) { showToast('Valeurs invalides', 'err'); return; }
  await saveConfigFields({ grill_window_minutes: w, grill_segment_size: s });
  showToast('Paramètres enregistrés', 'ok');
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

async function testPrinter(num) {
  try {
    const res = await fetch('/api/printers/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ printer: num }),
    });
    const data = await res.json();
    const key = `printer${num}`;
    if (data[key] === 'ok') showToast(`Imprimante ${num} : test OK`, 'ok');
    else showToast(`Imprimante ${num} : ${data[key]}`, 'err');
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
