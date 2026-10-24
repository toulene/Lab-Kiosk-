// Kiosk front end: login -> dashboard -> scan tray -> confirm -> done.
const $ = (sel) => document.querySelector(sel);
const state = { mode: null, scan: null, counts: {}, components: {}, holdings: {}, previewOn: false };
let idleTimer = null, doneTimer = null;

// ---------- helpers ----------
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/api/login") { showScreen("login"); throw new Error(data.error); }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function busy(text) {
  $("#busy").hidden = !text;
  if (text) $("#busy-text").textContent = text;
}

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("active", s.id === `screen-${name}`));
  state.previewOn = name === "scan" && !state.scan;
  if (state.previewOn) refreshPreview();
  clearInterval(doneTimer);
  if (name === "login") {
    $("#card-input").value = "";
    $("#card-input").focus();
  }
  resetIdle();
}

// Log out after a period with no touches, so the next person never lands in someone else's account.
function resetIdle() {
  clearTimeout(idleTimer);
  if (!$("#screen-login").classList.contains("active")) idleTimer = setTimeout(logout, window.IDLE_SECONDS * 1000);
}
["pointerdown", "keydown"].forEach((e) => document.addEventListener(e, resetIdle));

// Live view: load the next frame as soon as the last one arrives.
function refreshPreview() {
  if (!state.previewOn) return;
  const img = $("#camera-view");
  img.onload = () => setTimeout(refreshPreview, 100);
  img.onerror = () => setTimeout(refreshPreview, 1000);
  img.src = `/preview.jpg?t=${Date.now()}`;
  $("#camera-badge").textContent = "LIVE";
  $("#camera-badge").className = "badge";
}

// ---------- login ----------
const cardInput = $("#card-input");
document.querySelectorAll(".keypad button").forEach((b) => b.addEventListener("click", () => {
  const k = b.dataset.key;
  if (k === "clear") cardInput.value = "";
  else if (k === "back") cardInput.value = cardInput.value.slice(0, -1);
  else cardInput.value += k;
  cardInput.focus();
}));
// Keep the box focused so a keyboard-style RFID reader always has somewhere to type.
cardInput.addEventListener("blur", () => setTimeout(() => {
  if ($("#screen-login").classList.contains("active")) cardInput.focus();
}, 50));

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  const card = cardInput.value.trim();
  if (!card) return;
  try {
    await api("/api/login", { card_id: card });
    await loadDashboard();
  } catch (err) {
    $("#login-error").textContent = err.message;
    cardInput.value = "";
  }
});

async function logout() {
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  state.scan = null;
  showScreen("login");
}

// ---------- dashboard ----------
async function loadDashboard() {
  const d = await api("/api/me");
  state.components = d.components;
  state.holdings = Object.fromEntries(d.holdings.map((h) => [h.component, h.qty]));
  $("#user-name").textContent = `Hi, ${d.user.name}`;
  $("#user-meta").textContent = [d.user.roll_no, d.user.department, `Card ${d.user.card_id}`].filter(Boolean).join(" · ");

  $("#holdings").innerHTML = d.holdings.length
    ? d.holdings.map((h) => `<li><span>${esc(h.label)}</span><span class="qty">${h.qty}</span></li>`).join("")
    : `<li class="empty">Nothing issued right now.</li>`;

  $("#history").innerHTML = d.history.length
    ? d.history.map((t) => `<li><time>${esc(t.created_at)}</time><span class="tag ${t.action}">${t.action}</span>
        <span>${t.items.map((i) => `${i.qty} × ${esc(i.label)}`).join(", ")}</span></li>`).join("")
    : `<li class="empty">No activity yet.</li>`;
  showScreen("dashboard");
}

// ---------- scan ----------
function startScan(mode) {
  state.mode = mode;
  state.scan = null;
  $("#scan-title").textContent = mode === "issue" ? "Issue components" : "Return components";
  $("#scan-hint").textContent = mode === "issue"
    ? "Put everything you want to take in the tray."
    : "Put everything you are returning in the tray.";
  $("#scan-intro").hidden = false;
  $("#scan-result").hidden = true;
  showScreen("scan");
}

async function scanTray() {
  state.previewOn = false;
  busy("Detecting components…");
  try {
    const r = await api("/api/scan", {});
    state.scan = r;
    state.components = r.components;
    state.holdings = r.holdings;
    state.counts = { ...r.counts };
    const img = $("#camera-view");
    img.onload = img.onerror = null;
    img.src = r.image;
    $("#camera-badge").textContent = `${r.detections} found`;
    $("#camera-badge").className = "badge result";
    $("#scan-summary").textContent = `Scanned in ${r.seconds}s`;
    $("#scan-error").textContent = "";
    renderCounts();
    $("#scan-intro").hidden = true;
    $("#scan-result").hidden = false;
  } catch (err) {
    alert(err.message);
    state.previewOn = true;
    refreshPreview();
  } finally {
    busy(null);
  }
}

// Limit per part: stock left when issuing, what the user holds when returning.
function limitFor(name) {
  return state.mode === "issue" ? state.components[name].stock : (state.holdings[name] || 0);
}

function renderCounts() {
  // Detected parts first, then everything else at 0 so a missed part can be added by hand.
  const names = Object.keys(state.components).sort((a, b) => (state.counts[b] || 0) - (state.counts[a] || 0)
    || state.components[a].label.localeCompare(state.components[b].label));
  $("#scan-items").innerHTML = names.map((n) => {
    const qty = state.counts[n] || 0, limit = limitFor(n);
    const note = state.mode === "issue" ? `${limit} in stock` : `you have ${limit}`;
    return `<li class="${qty ? "" : "zero"} ${qty > limit ? "over" : ""}">
      <span class="name">${esc(state.components[n].label)}<small>${note}</small></span>
      <span class="stepper"><button data-step="-1" data-name="${n}">−</button><output>${qty}</output>
      <button data-step="1" data-name="${n}">+</button></span></li>`;
  }).join("");
  const total = Object.values(state.counts).reduce((a, b) => a + b, 0);
  const over = names.some((n) => (state.counts[n] || 0) > limitFor(n));
  $("#confirm-btn").disabled = total === 0 || over;
  $("#confirm-btn").textContent = total === 0 ? "Nothing to confirm"
    : `${state.mode === "issue" ? "Issue" : "Return"} ${total} item${total > 1 ? "s" : ""}`;
  $("#scan-error").textContent = over
    ? (state.mode === "issue" ? "Some counts are more than the lab has in stock." : "Some counts are more than you have issued.")
    : "";
}

$("#scan-items").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-step]");
  if (!b) return;
  const n = b.dataset.name;
  state.counts[n] = Math.max(0, (state.counts[n] || 0) + Number(b.dataset.step));
  renderCounts();
});

async function confirmScan() {
  busy("Saving…");
  try {
    const items = Object.fromEntries(Object.entries(state.counts).filter(([, q]) => q > 0));
    await api("/api/confirm", { action: state.mode, scan_id: state.scan.scan_id, items });
    showDone(items);
  } catch (err) {
    $("#scan-error").textContent = err.message;
  } finally {
    busy(null);
  }
}

function showDone(items) {
  const total = Object.values(items).reduce((a, b) => a + b, 0);
  $("#done-title").textContent = `${total} item${total > 1 ? "s" : ""} ${state.mode === "issue" ? "issued" : "returned"}`;
  $("#done-items").innerHTML = Object.entries(items)
    .map(([n, q]) => `<li>${q} × ${esc(state.components[n].label)}</li>`).join("");
  state.scan = null;
  showScreen("done");
  let left = 8;
  const tick = () => {
    $("#done-countdown").textContent = `Logging out in ${left}s`;
    if (left-- <= 0) logout();
  };
  tick();
  doneTimer = setInterval(tick, 1000);
}

// ---------- buttons ----------
document.addEventListener("click", (e) => {
  const action = e.target.closest("[data-action]")?.dataset.action;
  ({
    logout,
    issue: () => startScan("issue"),
    return: () => startScan("return"),
    back: () => loadDashboard(),
    dashboard: () => loadDashboard(),
    scan: scanTray,
    rescan: () => startScan(state.mode),
    confirm: confirmScan,
  })[action]?.();
});

// Show which model / camera the server is using, handy during setup.
fetch("/api/status").then((r) => r.json()).then((s) => {
  $("#status-line").textContent = `Model: ${s.detector} · Camera: ${s.camera}` + (s.camera_error ? ` (${s.camera_error})` : "");
}).catch(() => {});

showScreen("login");
