/**
 * app.js — Cognia Desktop renderer
 *
 * Communicates with the Python backend exclusively through window.cognia
 * (exposed by preload.js via contextBridge → ipcMain → HTTP).
 */

const chat       = document.getElementById("chat");
const promptEl   = document.getElementById("prompt");
const btnSend    = document.getElementById("btn-send");
const btnRoute   = document.getElementById("btn-route");
const btnStatus  = document.getElementById("btn-status");
const statusPanel = document.getElementById("status-panel");
const statusContent = document.getElementById("status-content");
const badge      = document.getElementById("backend-badge");

let backendReady = false;
let busy         = false;


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

window.cognia.onReady((data) => {
  backendReady = true;
  if (!data || data.status === "ready") {
    badge.textContent = "ready";
    badge.className   = "tag techne";
    setControls(false);
    appendSystem("Ready. Type a message and press Send.");
  } else {
    badge.textContent = "setup required";
    badge.className   = "tag rhetor";
    if (data.reason === "shards_missing" || data.shards === "missing") {
      appendSystem(
        "Model fragments not found.\n" +
        "Run the setup wizard to download the model fragments:\n\n" +
        "    cognia install-weights\n\n" +
        "Or open the setup window from the menu and follow the steps.\n" +
        "Then restart Cognia."
      );
    } else {
      appendSystem(
        "Inference backend not available.\n" +
        "Run the setup wizard to download model shards, or start Ollama:\n\n" +
        "    ollama serve && ollama pull " + (data.model_name || "llama3.2") + "\n\n" +
        "Then restart Cognia."
      );
    }
    setControls(false);
  }
});

window.cognia.onError((_msg) => {
  badge.textContent = "unavailable";
  badge.className   = "tag";
  badge.style.background = "#3a1a1a";
  badge.style.color = "var(--danger)";
  appendSystem("Cognia could not start. Please restart the application.");
});

window.cognia.onUpdateAvailable(() => {
  appendSystem("A new version is available. Restart Cognia to update.");
});


// ── Chat helpers ───────────────────────────────────────────────────────

function appendBubble(text, role) {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  el.textContent = text;
  chat.appendChild(el);
  scrollChat();
  return el;
}

function appendSystem(text) {
  appendBubble(text, "system");
}

function appendAI(result) {
  const wrap = document.createElement("div");
  wrap.style.alignSelf = "flex-start";
  wrap.style.maxWidth  = "82%";

  const bubble = document.createElement("div");
  bubble.className = "bubble ai";
  bubble.textContent = result.text;

  const meta = document.createElement("div");
  meta.className = "meta";
  const sm = result.sub_model || "?";
  const tag = document.createElement("span");
  tag.className = "tag " + sm;
  tag.textContent = sm.toUpperCase();
  meta.appendChild(tag);
  meta.appendChild(document.createTextNode(
    `${Math.round(result.confidence * 100)}% · ` +
    `${result.mode} · ${result.latency_ms?.toFixed(0)}ms`
  ));

  wrap.appendChild(bubble);
  wrap.appendChild(meta);
  chat.appendChild(wrap);
  scrollChat();
}

function appendRouteResult(d, prompt) {
  const wrap = document.createElement("div");
  wrap.style.alignSelf = "flex-start";
  wrap.style.maxWidth  = "82%";

  const bubble = document.createElement("div");
  bubble.className = "bubble ai";
  const sm = d.sub_model || "?";
  bubble.textContent =
    `Route for: "${prompt}"\n\n` +
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

function removeThinking() {
  document.getElementById("thinking")?.remove();
}

function scrollChat() {
  chat.scrollTop = chat.scrollHeight;
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

  appendBubble(text, "user");
  promptEl.value = "";
  autoResize();

  setControls(true);
  showThinking();

  // Bubble that grows token by token
  const streamWrap = document.createElement("div");
  streamWrap.style.alignSelf = "flex-start";
  streamWrap.style.maxWidth  = "82%";
  const streamBubble = document.createElement("div");
  streamBubble.className = "bubble ai";
  streamWrap.appendChild(streamBubble);
  // Meta line (filled on done)
  const streamMeta = document.createElement("div");
  streamMeta.className = "meta";
  streamWrap.appendChild(streamMeta);

  _cancelStream = window.cognia.inferStream(
    text,
    (token) => {
      removeThinking();
      if (!streamBubble.parentElement) chat.appendChild(streamWrap);
      streamBubble.textContent += token;
      scrollChat();
    },
    (final) => {
      _cancelStream = null;
      removeThinking();
      if (!streamBubble.parentElement) chat.appendChild(streamWrap);
      if (final.error) {
        appendSystem("Something went wrong. Please try again.");
        streamWrap.remove();
      } else {
        const sm = final.sub_model || "?";
        const streamTag = document.createElement("span");
        streamTag.className = "tag " + sm;
        streamTag.textContent = sm.toUpperCase();
        streamMeta.appendChild(streamTag);
        streamMeta.appendChild(document.createTextNode(
          `${Math.round((final.confidence || 0) * 100)}% · ` +
          `${final.mode} · ${final.latency_ms?.toFixed(0)}ms`
        ));
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
  } catch (_err) {
    appendSystem("Could not determine the best mode for this prompt. Please try again.");
  } finally {
    setControls(false);
    promptEl.focus();
  }
}


// ── Status panel ───────────────────────────────────────────────────────

let statusOpen = false;

async function toggleStatus() {
  statusOpen = !statusOpen;
  statusPanel.classList.toggle("visible", statusOpen);
  if (statusOpen) {
    statusContent.textContent = "Loading system information...";
    try {
      const s = await window.cognia.status();
      statusContent.textContent = _formatStatus(s);
    } catch (_err) {
      statusContent.textContent = "Could not load status.";
    }
  }
}


// ── Status formatter ──────────────────────────────────────────────────

function _formatStatus(s) {
  if (!s || typeof s !== "object") return "No status available.";
  const lines = [];
  const mode = s.mode || s.orchestrator_mode || "—";
  lines.push(`Mode:  ${mode}`);
  if (s.sub_model) lines.push(`Model: ${s.sub_model}`);
  if (typeof s.loaded_fragments === "number")
    lines.push(`Loaded: ${s.loaded_fragments} fragment(s)`);
  if (s.moe_balance && typeof s.moe_balance.max_ratio === "number")
    lines.push(`Balance: ${s.moe_balance.max_ratio.toFixed(2)}x max`);
  return lines.join("\n") || "System running.";
}


// ── Textarea auto-resize ───────────────────────────────────────────────

function autoResize() {
  promptEl.style.height = "42px";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 120) + "px";
}


// ── Event bindings ─────────────────────────────────────────────────────

btnSend.addEventListener("click", sendPrompt);
btnRoute.addEventListener("click", routePrompt);
btnStatus.addEventListener("click", toggleStatus);
document.getElementById("btn-feedback").addEventListener("click", () => {
  window.cognia.openFeedback();
});

promptEl.addEventListener("input", autoResize);

promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendPrompt();
  }
});
