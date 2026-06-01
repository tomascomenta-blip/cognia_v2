/**
 * preload.js
 * Exposes a minimal API to the renderer via contextBridge.
 * The renderer never has access to Node.js internals directly.
 */
const { contextBridge, ipcRenderer } = require("electron");

const API_PORT = process.env.COGNIA_DESKTOP_PORT || 8765;
const API_BASE = `http://127.0.0.1:${API_PORT}`;

contextBridge.exposeInMainWorld("cognia", {
  /** POST /infer (non-streaming) */
  infer: (prompt) => ipcRenderer.invoke("infer", prompt),

  /**
   * POST /infer-stream-v2 (SSE streaming with conversation history)
   * history: [{role, content}, ...] — previous turns (not including current prompt)
   * onToken(token: string) called for each token chunk
   * onDone({ done, sub_model, confidence, latency_ms, mode }) called at the end
   * Returns a cancel() function.
   */
  inferStream: (prompt, history, onToken, onDone) => {
    const controller = new AbortController();
    let finished = false;

    fetch(`${API_BASE}/infer-stream-v2`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ prompt, history }),
      signal:  controller.signal,
    }).then(async (response) => {
      const reader  = response.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            const data = JSON.parse(raw);
            if (data.done) {
              finished = true;
              onDone(data);
              return;
            } else {
              onToken(data.token);
            }
          } catch (_) {}
        }
      }
      if (!finished) onDone({ done: true, sub_model: "llama", confidence: 1, latency_ms: 0, mode: "llama.cpp" });
    }).catch((err) => {
      if (err.name !== "AbortError") onDone({ error: err.message });
    });

    return () => controller.abort();
  },

  /** GET /route */
  route: (prompt) => ipcRenderer.invoke("route", prompt),

  /** GET /status */
  status: () => ipcRenderer.invoke("status"),

  /** Listen for backend-ready event — cb receives { status, ollama, model, model_name } */
  onReady: (cb) => ipcRenderer.on("backend-ready", (_e, data) => cb(data)),

  /** Listen for backend errors */
  onError: (cb) => ipcRenderer.on("backend-error", (_e, msg) => cb(msg)),

  /** Open GitHub Issues in the system browser */
  openFeedback: () => ipcRenderer.invoke("open-feedback"),

  /** Listen for auto-update downloaded event */
  onUpdateAvailable: (cb) => ipcRenderer.on("update-available", cb),

  /** Setup wizard — only active when setup.html is loaded */
  setup: {
    run:          (opts) => ipcRenderer.invoke("setup:run", opts),
    launch:       ()     => ipcRenderer.invoke("setup:launch"),
    openExternal: (url)  => ipcRenderer.invoke("setup:open-external", url),
    onProgress:   (cb)   => ipcRenderer.on("setup:progress", (_e, d) => cb(d)),
    onDone:       (cb)   => ipcRenderer.once("setup:done",   ()       => cb()),
    onError:      (cb)   => ipcRenderer.once("setup:error",  (_e, m)  => cb(m)),
  },
});
