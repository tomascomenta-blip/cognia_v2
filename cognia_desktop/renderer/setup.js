"use strict";

const PHASES = {
  check_python:    "check_python",
  install_deps:    "install_deps",
  generate_keys:   "generate_keys",
  write_env:       "generate_keys",   // maps to same row
  register_node:   "register_node",
  download_shards: "download_shards",
  verify_shards:   "verify_shards",
};

const COORDINATOR_URL = "https://cognia-coordinator-production.up.railway.app";

let setupOpts = { coordinatorMode: "swarm", coordinatorUrl: COORDINATOR_URL };
let currentShardProgress = {};   // shard index -> { done, total }

// ── Navigation ─────────────────────────────────────────────────────────

function showStep(n) {
  document.querySelectorAll(".step").forEach((el) => el.classList.remove("active"));
  document.getElementById(`step-${n}`).classList.add("active");
}

// ── Phase list helpers ─────────────────────────────────────────────────

function phaseRow(phase) {
  return document.querySelector(`.phase-item[data-phase="${phase}"]`);
}

function setPhaseState(phase, state, detail) {
  const row = phaseRow(phase);
  if (!row) return;
  const icon   = row.querySelector(".phase-icon");
  const detEl  = row.querySelector(".detail");

  icon.className = "phase-icon";
  if (state === "ok")      { icon.textContent = "[*]"; icon.classList.add("ok"); }
  else if (state === "err"){ icon.textContent = "[!]"; icon.classList.add("err"); }
  else if (state === "run"){ icon.textContent = "[-]"; }
  else                     { icon.textContent = "[ ]"; }

  if (detail !== undefined) detEl.textContent = detail;
}

function updateShardProgress(shard, bytesDone, bytesTotal) {
  currentShardProgress[shard] = { done: bytesDone, total: bytesTotal };

  const row = phaseRow("download_shards");
  if (!row) return;

  const wrap = row.querySelector(".progress-bar-wrap");
  const fill = document.getElementById("shard-progress");
  const det  = row.querySelector(".detail");
  wrap.style.display = "block";

  const totalShards = 4;
  const completedShards = Object.values(currentShardProgress).filter(
    (s) => s.done >= s.total && s.total > 0
  ).length;

  if (bytesTotal > 0) {
    const pct = Math.min(100, Math.round(bytesDone / bytesTotal * 100));
    fill.style.width = `${pct}%`;
    det.textContent = `shard ${shard + 1}/${totalShards}  ${pct}%`;
  } else {
    det.textContent = `shard ${shard + 1}/${totalShards}`;
  }
}

// ── Progress handler ───────────────────────────────────────────────────

function onProgress(msg) {
  const phase  = PHASES[msg.phase] || msg.phase;
  const status = msg.status;

  if (status === "progress" && msg.phase === "download_shards") {
    setPhaseState("download_shards", "run");
    updateShardProgress(msg.shard, msg.bytes_done || 0, msg.bytes_total || 0);
    return;
  }

  if (status === "ok" && msg.phase === "download_shards") {
    const fill = document.getElementById("shard-progress");
    fill.style.width = "100%";
    setPhaseState("download_shards", "ok", "completado");
    return;
  }

  if (status === "ok" || status === "skip") {
    setPhaseState(phase, "ok", msg.detail || "");
    return;
  }

  if (status === "running") {
    setPhaseState(phase, "run", "");
    return;
  }

  if (status === "error") {
    setPhaseState(phase, "err", msg.detail || "error");
    return;
  }
}

function onDone() {
  document.getElementById("result-title").textContent = "Configuracion completa";
  document.getElementById("result-msg").textContent   = "Cognia esta listo.";
  document.getElementById("result-msg").classList.remove("error");
  document.getElementById("result-hint").textContent  = "";
  document.getElementById("btn-launch").style.display = "inline-block";
  showStep(4);
}

function onError(msg) {
  document.getElementById("result-title").textContent = "Error de configuracion";
  document.getElementById("result-msg").textContent   = `[!] ${msg}`;
  document.getElementById("result-msg").classList.add("error");

  const isPythonError = msg && msg.toLowerCase().includes("python");
  if (isPythonError) {
    document.getElementById("result-hint").textContent =
      "Si Python no esta instalado, descargalo desde python.org, reinstalalo y vuelve a abrir Cognia.";
    document.getElementById("btn-open-python").style.display = "inline-block";
  }
  document.getElementById("btn-retry").style.display = "inline-block";
  document.getElementById("btn-quit").style.display  = "inline-block";
  showStep(4);
}

// ── Wiring ─────────────────────────────────────────────────────────────

document.getElementById("btn-begin").addEventListener("click", () => showStep(2));

document.getElementById("btn-back-1").addEventListener("click", () => showStep(1));

document.getElementById("btn-continue").addEventListener("click", () => {
  const urlInput = document.getElementById("coordinator-url-input");
  const coordinatorUrl = (urlInput && urlInput.value.trim()) ? urlInput.value.trim() : COORDINATOR_URL;
  setupOpts = { coordinatorMode: "swarm", coordinatorUrl };

  // Always show register_node row (swarm-only)
  const registerRow = document.querySelector('.phase-item[data-phase="register_node"]');
  registerRow.style.display = "flex";

  showStep(3);

  window.cognia.setup.onProgress(onProgress);
  window.cognia.setup.onDone(onDone);
  window.cognia.setup.onError(onError);
  window.cognia.setup.run(setupOpts);
});

document.getElementById("btn-launch").addEventListener("click", () => {
  window.cognia.setup.launch();
});

document.getElementById("btn-open-python").addEventListener("click", () => {
  window.cognia.setup.openExternal("https://python.org/downloads");
});

document.getElementById("btn-retry").addEventListener("click", () => {
  document.querySelectorAll(".phase-icon").forEach((el) => {
    el.textContent = "[ ]";
    el.className   = "phase-icon";
  });
  document.querySelectorAll(".detail").forEach((el) => { el.textContent = ""; });
  const fill = document.getElementById("shard-progress");
  if (fill) fill.style.width = "0%";
  currentShardProgress = {};

  // Ensure register_node row is visible (swarm-only)
  const registerRow = document.querySelector('.phase-item[data-phase="register_node"]');
  registerRow.style.display = "flex";

  showStep(3);

  window.cognia.setup.onProgress(onProgress);
  window.cognia.setup.onDone(onDone);
  window.cognia.setup.onError(onError);
  window.cognia.setup.run(setupOpts);
});

document.getElementById("btn-quit").addEventListener("click", () => {
  window.close();
});
