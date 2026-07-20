/**
 * app.js — Cognia Desktop renderer
 *
 * Communicates with the Python backend exclusively through window.cognia
 * (exposed by preload.js via contextBridge → ipcMain → HTTP).
 */

// ── Element refs ───────────────────────────────────────────────────────
const chat          = document.getElementById("chat");
const promptEl      = document.getElementById("prompt");
const btnSend       = document.getElementById("btn-send");
const btnRoute      = document.getElementById("btn-route");
const btnStatus     = document.getElementById("btn-status");
const statusContent = document.getElementById("status-content");
const badge         = document.getElementById("backend-badge");
const perfBar       = document.getElementById("perf-bar");
const charCounter   = document.getElementById("char-counter");

promptEl.addEventListener("input", () => {
  const len = promptEl.value.length;
  if (charCounter) {
    charCounter.textContent = len + "/4096";
    charCounter.style.color = len > 4096 ? "#ef4444" : len > 3800 ? "#f97316" : "";
    charCounter.style.opacity = len > 0 ? "0.7" : "0.4";
  }
});

let backendReady = false;
let busy         = false;
const history    = [];   // [{role: "user"|"assistant", content: string}]


// ── Sidebar navigation ─────────────────────────────────────────────────

document.querySelectorAll(".nav-item[data-panel]").forEach(btn => {
  btn.addEventListener("click", () => {
    const panelId = "panel-" + btn.dataset.panel;
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    const target = document.getElementById(panelId);
    if (target) target.classList.add("active");
    btn.classList.add("active");
    if (btn.dataset.panel === "status")   refreshStatus();
    if (btn.dataset.panel === "nodes")    refreshNodes();
    if (btn.dataset.panel === "skills")   refreshSkills();
    if (btn.dataset.panel === "tools")    loadDirectory('.');
    if (btn.dataset.panel === "settings") loadSettingsPanel();
  });
});

// Status refresh (also wired to Refresh button)
async function refreshStatus() {
  if (!statusContent) return;
  statusContent.textContent = "Loading...";
  try {
    const s = await window.cognia.status();
    statusContent.textContent = _formatStatus(s);
    const modeEl = document.getElementById("settings-mode");
    if (modeEl) modeEl.textContent = s?.mode || s?.orchestrator_mode || "—";
  } catch (_) {
    statusContent.textContent = "Could not load status. Is the backend running?";
  }
}

// Nodes refresh
async function refreshNodes() {
  const el = document.getElementById("nodes-content");
  if (!el) return;
  el.innerHTML = "<p class='placeholder-text'>Loading...</p>";
  try {
    const s = await window.cognia.status();
    const frags = typeof s?.loaded_fragments === "number"
      ? s.loaded_fragments + " shard(s) loaded"
      : "—";
    const mode = s?.mode || s?.orchestrator_mode || "—";
    const balance = s?.moe_balance?.max_ratio != null
      ? s.moe_balance.max_ratio.toFixed(2) + "x max imbalance"
      : "—";
    el.innerHTML = `
      <div class="settings-row"><span class="settings-key">Shards</span><span class="settings-val">${frags}</span></div>
      <div class="settings-row"><span class="settings-key">Mode</span><span class="settings-val">${mode}</span></div>
      <div class="settings-row"><span class="settings-key">Balance</span><span class="settings-val">${balance}</span></div>
    `;
  } catch (_) {
    el.innerHTML = "<p class='placeholder-text'>Could not load node data.</p>";
  }
}


// ── Skills panel ──────────────────────────────────────────────────────

async function refreshSkills() {
  const el = document.getElementById("skills-content");
  if (!el) return;
  el.innerHTML = "<p class='placeholder-text'>Loading...</p>";
  try {
    const res = await fetch("http://127.0.0.1:8765/skills");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const skills = data.skills || [];
    if (!skills.length) {
      el.innerHTML = "<p class='placeholder-text'>No skills found. Create one with <code>/skill-nuevo &lt;name&gt;</code> in the CLI.</p>";
      return;
    }
    el.innerHTML = skills.map(s => `
      <div class="skill-card">
        <div class="skill-info">
          <span class="skill-name">${_esc(s.name)}</span>
          <span class="skill-desc">${_esc(s.description || "")}</span>
        </div>
        <button class="btn-ghost skill-use" data-skill="${_esc(s.name)}">Use</button>
      </div>
    `).join("");
    el.querySelectorAll(".skill-use").forEach(btn => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.skill;
        try {
          const r = await fetch(`http://127.0.0.1:8765/skills/${encodeURIComponent(name)}`);
          if (!r.ok) throw new Error("HTTP " + r.status);
          const d = await r.json();
          const lines = d.content.split("\n");
          let inFront = false, body = [], pastFront = false;
          for (const line of lines) {
            if (line.trim() === "---") { inFront = !inFront; if (!inFront) { pastFront = true; } continue; }
            if (pastFront) body.push(line);
          }
          const prompt = body.join("\n").replace(/^\n+/, "");
          promptEl.value = prompt;
          promptEl.dispatchEvent(new Event("input"));
          document.querySelector(".nav-item[data-panel='chat']")?.click();
          promptEl.focus();
        } catch (e) {
          alert("Could not load skill: " + e.message);
        }
      });
    });
  } catch (e) {
    el.innerHTML = "<p class='placeholder-text'>Could not load skills. Is the backend running?</p>";
  }
}

function _esc(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── First-run privacy consent ──────────────────────────────────────────

(function checkPrivacyConsent() {
  if (!localStorage.getItem("privacyConsent_v1")) {
    const modal = document.getElementById("privacy-modal");
    modal.classList.add("visible");
    document.getElementById("btn-privacy-accept").addEventListener("click", () => {
      localStorage.setItem("privacyConsent_v1", "accepted");
      modal.classList.remove("visible");
    });
  }
})();


// ── Backend lifecycle ──────────────────────────────────────────────────

const _SESSION_ID = "default";

async function _loadHistory() {
  try {
    const res = await fetch(`http://127.0.0.1:8765/chat/history?session_id=${_SESSION_ID}`);
    if (!res.ok) return;
    const data = await res.json();
    for (const msg of (data.messages || [])) {
      if (msg.role === "user") {
        appendBubble(msg.content, "user", null);
      } else if (msg.role === "assistant") {
        appendBubble(msg.content, "ai", null);
      }
      history.push({ role: msg.role, content: msg.content });
    }
    if (history.length > 0) scrollChat();
  } catch (_) {}
}

async function _saveHistory() {
  try {
    await fetch("http://127.0.0.1:8765/chat/history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: _SESSION_ID, messages: history }),
    });
  } catch (_) {}
}

async function _clearHistory() {
  try {
    await fetch(`http://127.0.0.1:8765/chat/history?session_id=${_SESSION_ID}`, { method: "DELETE" });
  } catch (_) {}
}

window.cognia.onReady((data) => {
  backendReady = true;
  if (!data || data.status === "ready") {
    badge.textContent = "ready";
    badge.className   = "badge ready";
    setControls(false);
    _loadHistory().then(() => {
      if (history.length === 0) appendSystem("Ready. Type a message and press Send.");
    });
  } else {
    badge.textContent = "setup required";
    badge.className   = "badge";
    if (data.reason === "shards_missing" || data.shards === "missing") {
      appendSystem(
        "Model fragments not found.\n" +
        "Run the setup wizard to download the model:\n\n" +
        "    cognia install-weights\n\n" +
        "Then restart Cognia."
      );
    } else {
      appendSystem(
        "Inference backend not available.\n" +
        "Start Ollama or run the setup wizard:\n\n" +
        "    ollama serve && ollama pull " + (data.model_name || "llama3.2") + "\n\n" +
        "Then restart Cognia."
      );
    }
    setControls(false);
  }
});

window.cognia.onError((_msg) => {
  badge.textContent = "unavailable";
  badge.className   = "badge error";
  appendSystem("Cognia could not start. Please restart the application.");
});

window.cognia.onUpdateAvailable(() => {
  appendSystem("A new version is available. Restart Cognia to update.");
});


// ── Chat helpers ───────────────────────────────────────────────────────

function _makeTimeSpan(timestamp) {
  const span = document.createElement("span");
  span.style.cssText = "font-size:10px;opacity:0.5;margin-left:8px;";
  span.textContent = timestamp === null ? "anteriormente"
    : timestamp !== undefined ? timestamp
    : new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  return span;
}

function appendBubble(text, role, timestamp) {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  if (role === "ai") {
    const textSpan = document.createElement("span");
    textSpan.innerHTML = mdToHtml(text);
    el.appendChild(textSpan);
    const btn = document.createElement("button");
    btn.textContent = "Copy";
    btn.style.cssText = "display:block;margin-top:6px;font-size:11px;padding:2px 8px;cursor:pointer;opacity:0.6;border:1px solid currentColor;border-radius:4px;background:transparent;color:inherit;";
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy"; }, 1500);
      });
    });
    el.appendChild(btn);
    el.appendChild(_makeTimeSpan(timestamp));
  } else {
    el.appendChild(document.createTextNode(text));
    if (role === "user") el.appendChild(_makeTimeSpan(timestamp));
  }
  chat.appendChild(el);
  scrollChat();
  return el;
}

function appendSystem(text) { appendBubble(text, "system"); }

function appendAI(result) {
  const wrap   = document.createElement("div");
  wrap.style.alignSelf = "flex-start";
  wrap.style.maxWidth  = "76%";

  const bubble = document.createElement("div");
  bubble.className = "bubble ai";
  bubble.textContent = result.text;

  const meta = document.createElement("div");
  meta.className = "meta";
  const sm  = result.sub_model || "?";
  const tag = document.createElement("span");
  tag.className = "tag " + sm;
  tag.textContent = sm.toUpperCase();
  meta.appendChild(tag);
  meta.appendChild(document.createTextNode(
    `${Math.round(result.confidence * 100)}% · ${result.mode} · ${result.latency_ms?.toFixed(0)}ms`
  ));

  wrap.appendChild(bubble);
  wrap.appendChild(meta);
  chat.appendChild(wrap);
  scrollChat();
}

function appendRouteResult(d, prompt) {
  const wrap   = document.createElement("div");
  wrap.style.alignSelf = "flex-start";
  wrap.style.maxWidth  = "76%";

  const bubble = document.createElement("div");
  bubble.className = "bubble ai";
  const sm = d.sub_model || "?";
  bubble.textContent =
    `Route: "${prompt}"\n\n` +
    `Sub-model : ${sm.toUpperCase()}\n` +
    `Confidence: ${Math.round(d.confidence * 100)}%\n` +
    `Scores    : ${JSON.stringify(d.scores)}\n` +
    `Reason    : ${d.reason}`;

  const meta = document.createElement("div");
  meta.className = "meta";
  const routeTag = document.createElement("span");
  routeTag.className = "tag " + sm;
  routeTag.textContent = sm.toUpperCase();
  meta.appendChild(routeTag);
  meta.appendChild(document.createTextNode("route-only"));

  wrap.appendChild(bubble);
  wrap.appendChild(meta);
  chat.appendChild(wrap);
  scrollChat();
}

function showThinking() {
  const el = document.createElement("div");
  el.className = "thinking";
  el.id = "thinking";
  el.innerHTML = "<span></span><span></span><span></span>";
  chat.appendChild(el);
  scrollChat();
  return el;
}

function removeThinking() { document.getElementById("thinking")?.remove(); }
function scrollChat()     { chat.scrollTop = chat.scrollHeight; }

function mdToHtml(text) {
  let s = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  s = s.replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>");
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)/g, "<em>$1</em>");
  s = s.replace(/^#{1,3} (.+)$/gm, "<strong>$1</strong><br>");
  s = s.replace(/^[-*] (.+)$/gm, "&bull; $1");
  s = s.replace(/\n/g, "<br>");
  return s;
}

function setControls(isBusy) {
  busy = isBusy;
  btnSend.disabled  = isBusy || !backendReady;
  btnRoute.disabled = isBusy || !backendReady;
}


// ── Send (streaming) ───────────────────────────────────────────────────

let _cancelStream = null;

function sendPrompt() {
  const text = promptEl.value.trim();
  if (!text || busy || !backendReady) return;

  history.push({ role: "user", content: text });
  appendBubble(text, "user");
  promptEl.value = "";
  autoResize();
  setControls(true);
  showThinking();

  const streamWrap   = document.createElement("div");
  streamWrap.style.alignSelf = "flex-start";
  streamWrap.style.maxWidth  = "76%";
  const streamBubble = document.createElement("div");
  streamBubble.className = "bubble ai";
  streamWrap.appendChild(streamBubble);
  const streamMeta = document.createElement("div");
  streamMeta.className = "meta";
  streamWrap.appendChild(streamMeta);

  // Pass history without the current turn (API appends prompt separately)
  const historySnapshot = history.slice(0, -1);
  const _streamStart = Date.now();

  _cancelStream = window.cognia.inferStream(
    text,
    historySnapshot,
    (token) => {
      removeThinking();
      if (!streamWrap.parentElement) chat.appendChild(streamWrap);
      streamBubble.textContent += token;
      scrollChat();
    },
    (final) => {
      _cancelStream = null;
      removeThinking();
      if (!streamWrap.parentElement) chat.appendChild(streamWrap);
      if (final.error) {
        history.pop(); // remove failed user turn
        appendSystem(
          final.error.includes("hard") || final.error.includes("shard")
            ? "Inference failed: " + final.error
            : "Error processing response. Check backend logs."
        );
        streamWrap.remove();
      } else {
        const assistantText = streamBubble.textContent;
        streamBubble.innerHTML = mdToHtml(assistantText);
        history.push({ role: "assistant", content: assistantText });
        _saveHistory();
        const sm = final.sub_model || "?";
        const tag = document.createElement("span");
        tag.className = "tag " + sm;
        tag.textContent = sm.toUpperCase();
        streamMeta.appendChild(tag);
        streamMeta.appendChild(document.createTextNode(
          `${Math.round((final.confidence || 0) * 100)}% · ${final.mode} · ${final.latency_ms?.toFixed(0)}ms`
        ));

        if (final.route_reason && final.route_reason !== "llama.cpp") {
          const reasonEl = document.createElement("div");
          reasonEl.style.cssText = "font-size:10px;opacity:0.45;margin-top:2px;font-style:italic;";
          reasonEl.textContent = final.route_reason;
          streamWrap.appendChild(reasonEl);
        }

        const copyBtn = document.createElement("button");
        copyBtn.textContent = "Copy";
        copyBtn.style.cssText = "display:block;margin-top:4px;font-size:11px;padding:2px 8px;cursor:pointer;opacity:0.6;border:1px solid currentColor;border-radius:4px;background:transparent;color:inherit;";
        copyBtn.addEventListener("click", () => {
          navigator.clipboard.writeText(assistantText).then(() => {
            copyBtn.textContent = "Copied!";
            setTimeout(() => { copyBtn.textContent = "Copy"; }, 1500);
          });
        });
        streamWrap.appendChild(copyBtn);
        streamWrap.appendChild(_makeTimeSpan());

        if (perfBar) {
          const elapsed_ms = final.latency_ms ?? (Date.now() - _streamStart);
          const wordCount  = assistantText.trim().split(/\s+/).filter(Boolean).length;
          const tok_s      = elapsed_ms > 0 ? (wordCount / (elapsed_ms / 1000)).toFixed(1) : "—";
          const parts      = [`Backend: ${final.mode || "—"}`];
          parts.push(`~${tok_s} tok/s`);
          perfBar.textContent = parts.join(" | ");
        }
      }
      setControls(false);
      promptEl.focus();
    },
  );
}

async function routePrompt() {
  const text = promptEl.value.trim();
  if (!text || busy || !backendReady) return;
  setControls(true);
  try {
    const d = await window.cognia.route(text);
    appendRouteResult(d, text);
  } catch (_) {
    appendSystem("Could not determine the best mode for this prompt.");
  } finally {
    setControls(false);
    promptEl.focus();
  }
}


// ── Status (backward compat — btn-status is now "Refresh" in status panel) ──

if (btnStatus) {
  btnStatus.addEventListener("click", refreshStatus);
}

// Legacy: _formatStatus kept for compatibility
function _formatStatus(s) {
  if (!s || typeof s !== "object") return "No status available.";
  const lines = [];
  const mode = s.mode || s.orchestrator_mode || "—";
  lines.push(`Mode:     ${mode}`);
  if (s.sub_model)                         lines.push(`Model:    ${s.sub_model}`);
  if (typeof s.loaded_fragments === "number") lines.push(`Loaded:   ${s.loaded_fragments} fragment(s)`);
  if (s.moe_balance?.max_ratio != null)    lines.push(`Balance:  ${s.moe_balance.max_ratio.toFixed(2)}x max`);
  return lines.join("\n") || "System running.";
}


// ── Textarea auto-resize ───────────────────────────────────────────────

function autoResize() {
  promptEl.style.height = "36px";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 120) + "px";
}


// ── Event bindings ─────────────────────────────────────────────────────

btnSend.addEventListener("click", sendPrompt);
btnRoute.addEventListener("click", routePrompt);

const btnClearChat = document.getElementById("btn-clear-chat");
if (btnClearChat) {
  btnClearChat.addEventListener("click", () => {
    chat.innerHTML = "";
    history.length = 0;
    _clearHistory();
  });
}

const btnExportChat = document.getElementById("btn-export-chat");
if (btnExportChat) {
  btnExportChat.addEventListener("click", () => {
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10);
    const lines = [
      "# Cognia Chat Export",
      `_Exportado: ${now.toLocaleString()}_`,
      "",
    ];
    for (const msg of history) {
      const label = msg.role === "user" ? "**Usuario:**" : "**Cognia:**";
      lines.push(`${label} ${msg.content}`, "");
    }
    const md = lines.join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    a.download = `cognia-chat-${dateStr}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

const feedbackBtn = document.getElementById("btn-feedback");
if (feedbackBtn) {
  feedbackBtn.addEventListener("click", () => window.cognia.openFeedback());
}

// ── Network status polling ─────────────────────────────────────────────

const _networkStatusEl = document.getElementById("network-status");

async function _refreshNetworkStatus() {
  if (!_networkStatusEl) return;
  try {
    const res = await fetch("http://127.0.0.1:8765/network/status");
    if (!res.ok) throw new Error("http " + res.status);
    const d = await res.json();
    if (d.online === false) {
      _networkStatusEl.textContent = "Network: offline";
    } else {
      const nodes = d.active_nodes ?? d.nodes ?? d.connected_nodes;
      _networkStatusEl.textContent = nodes != null
        ? `Network: ${nodes} node${nodes !== 1 ? "s" : ""} online`
        : "Network: online";
    }
  } catch (_) {
    _networkStatusEl.textContent = "Network: offline";
  }
}

_refreshNetworkStatus();
setInterval(_refreshNetworkStatus, 30000);


promptEl.addEventListener("input", autoResize);
promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendPrompt();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "l" && e.ctrlKey) {
    e.preventDefault();
    chat.innerHTML = "";
    history.length = 0;
    _clearHistory();
    promptEl.focus();
  }
  // Ctrl+Enter or Cmd+Enter: send message
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    sendPrompt();
    return;
  }
  // Ctrl+K: clear chat
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    if (confirm("Limpiar el chat?")) {
      chat.innerHTML = "";
      history.length = 0;
      _saveHistory();
      appendSystem("Chat limpiado.");
    }
    return;
  }
  // Escape: cancel stream
  if (e.key === "Escape" && _cancelStream) {
    e.preventDefault();
    _cancelStream();
    _cancelStream = null;
    removeThinking();
    appendSystem("Respuesta cancelada.");
    return;
  }
});


// ── Tools panel ──────────────────────────────────────────────────────────────
let _editorCurrentPath = null;

async function loadDirectory(path) {
  path = path || '.';
  try {
    const r = await fetch('http://127.0.0.1:8765/files/list?path=' + encodeURIComponent(path));
    const data = await r.json();
    document.getElementById('browser-path').textContent = data.path || path;
    const list = document.getElementById('file-list');
    list.innerHTML = '';
    // Up button if not root
    if (data.path && data.path !== '.') {
      const up = document.createElement('div');
      up.className = 'file-entry dir-entry';
      up.textContent = '.. (subir)';
      const parentPath = data.path.split('/').slice(0, -1).join('/') || '.';
      up.addEventListener('click', () => loadDirectory(parentPath));
      list.appendChild(up);
    }
    (data.entries || []).forEach(e => {
      const row = document.createElement('div');
      row.className = 'file-entry ' + (e.type === 'dir' ? 'dir-entry' : 'file-entry-item');
      const sizeStr = e.type === 'file' && e.size != null
        ? (' (' + (e.size > 1024 ? (e.size/1024).toFixed(1)+'KB' : e.size+'B') + ')')
        : '';
      row.textContent = (e.type === 'dir' ? '[D] ' : '[F] ') + e.name + sizeStr;
      if (e.type === 'dir') {
        row.addEventListener('click', () => loadDirectory(e.path));
      } else {
        row.addEventListener('click', () => openFile(e.path, e.name));
      }
      list.appendChild(row);
    });
  } catch(err) {
    const list = document.getElementById('file-list');
    if (list) list.textContent = 'Error: ' + err.message;
  }
}

async function openFile(path, name) {
  try {
    const r = await fetch('http://127.0.0.1:8765/files/read?path=' + encodeURIComponent(path));
    const data = await r.json();
    _editorCurrentPath = path;
    document.getElementById('editor-filename').textContent = name || path;
    const ed = document.getElementById('file-editor');
    ed.value = data.content || '';
    ed.disabled = false;
    document.getElementById('btn-send-to-chat').disabled = false;
    document.getElementById('btn-save-file').disabled = false;
    if (data.truncated) {
      document.getElementById('editor-filename').textContent += ' [truncado a 100KB]';
    }
  } catch(err) {
    alert('Error abriendo archivo: ' + err.message);
  }
}

const _btnRefreshFiles = document.getElementById('btn-refresh-files');
if (_btnRefreshFiles) {
  _btnRefreshFiles.addEventListener('click', () => {
    loadDirectory(document.getElementById('browser-path').textContent);
  });
}

const _btnSendToChat = document.getElementById('btn-send-to-chat');
if (_btnSendToChat) {
  _btnSendToChat.addEventListener('click', () => {
    const content = document.getElementById('file-editor').value;
    if (!content) return;
    const fname = _editorCurrentPath || 'archivo';
    promptEl.value = 'Lee este archivo (' + fname + '):\n\n' + content.slice(0, 4000);
    promptEl.dispatchEvent(new Event('input'));
    document.querySelector('.nav-item[data-panel="chat"]').click();
    promptEl.focus();
  });
}

const _btnSaveFile = document.getElementById('btn-save-file');
if (_btnSaveFile) {
  _btnSaveFile.addEventListener('click', async () => {
    if (!_editorCurrentPath) return;
    const content = document.getElementById('file-editor').value;
    try {
      const r = await fetch('http://127.0.0.1:8765/files/write', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: _editorCurrentPath, content})
      });
      const data = await r.json();
      if (data.ok) {
        const btn = document.getElementById('btn-save-file');
        btn.textContent = 'Guardado!';
        setTimeout(() => { btn.textContent = 'Guardar'; }, 1500);
      }
    } catch(err) {
      alert('Error guardando: ' + err.message);
    }
  });
}


// ── Agent modal ───────────────────────────────────────────────────────────────

const agentModal     = document.getElementById('agent-modal');
const agentTaskInput = document.getElementById('agent-task-input');
const agentRunBtn    = document.getElementById('agent-run-btn');
const agentCancelBtn = document.getElementById('agent-cancel-btn');
const agentResult    = document.getElementById('agent-result');
const navAgent       = document.getElementById('nav-agent');

if (navAgent) {
  navAgent.addEventListener('click', () => {
    agentModal.style.display = 'flex';
    agentTaskInput.value = '';
    agentResult.style.display = 'none';
    agentTaskInput.focus();
  });
}
if (agentCancelBtn) {
  agentCancelBtn.addEventListener('click', () => {
    agentModal.style.display = 'none';
  });
}
if (agentRunBtn) {
  agentRunBtn.addEventListener('click', async () => {
    const task = agentTaskInput.value.trim();
    if (!task) return;
    agentRunBtn.disabled = true;
    agentRunBtn.textContent = 'Ejecutando...';
    agentResult.style.display = 'none';
    try {
      const resp = await fetch(`${window._backendUrl || 'http://127.0.0.1:8765'}/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task })
      });
      const data = await resp.json();
      agentResult.textContent = data.result || data.detail || 'Sin resultado';
      agentResult.style.display = 'block';
    } catch (e) {
      agentResult.textContent = 'Error: ' + e.message;
      agentResult.style.display = 'block';
    } finally {
      agentRunBtn.disabled = false;
      agentRunBtn.textContent = 'Ejecutar';
    }
  });
}


// ── Settings panel: personalization, mode, theme ──────────────────────
const _SETTINGS_API = "http://127.0.0.1:8765";

function applyTheme(theme) {
  document.body.classList.toggle("light", theme === "light");
  try { localStorage.setItem("cognia_theme", theme); } catch (_) {}
}

async function loadSettingsPanel() {
  const themeSel = document.getElementById("set-theme");
  if (themeSel) { try { themeSel.value = localStorage.getItem("cognia_theme") || "dark"; } catch (_) {} }
  try {
    const r = await fetch(`${_SETTINGS_API}/settings`);
    if (!r.ok) return;
    const s = await r.json();
    const n  = document.getElementById("set-name");  if (n)  n.value  = s.name  || "";
    const l  = document.getElementById("set-lang");  if (l)  l.value  = s.lang  || "";
    const st = document.getElementById("set-style"); if (st) st.value = s.style || "";
    const m  = document.getElementById("set-mode");  if (m && s.mode) m.value = s.mode;
  } catch (_) {}
}

(function wireSettingsPanel() {
  const save = document.getElementById("btn-save-personalization");
  if (save) save.addEventListener("click", async () => {
    const note = document.getElementById("set-saved");
    const payload = {
      name:  document.getElementById("set-name")?.value  || "",
      lang:  document.getElementById("set-lang")?.value  || "",
      style: document.getElementById("set-style")?.value || "",
    };
    try {
      const r = await fetch(`${_SETTINGS_API}/settings`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (note) note.textContent = r.ok ? "Guardado." : "Error al guardar";
    } catch (_) { if (note) note.textContent = "Backend no disponible"; }
    setTimeout(() => { if (note) note.textContent = ""; }, 2500);
  });

  const modeSel = document.getElementById("set-mode");
  if (modeSel) modeSel.addEventListener("change", async () => {
    try {
      await fetch(`${_SETTINGS_API}/mode`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: modeSel.value }),
      });
    } catch (_) {}
  });

  const themeSel = document.getElementById("set-theme");
  if (themeSel) themeSel.addEventListener("change", () => applyTheme(themeSel.value));
})();

// Apply the saved theme as soon as the app loads.
try { applyTheme(localStorage.getItem("cognia_theme") || "dark"); } catch (_) {}
