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
   * GET /infer-stream (SSE streaming)
   * onToken(token: string) called for each token chunk
   * onDone({ done, sub_model, confidence, latency_ms, mode }) called at the end
   * Returns a cancel() function.
   */
  inferStream: (prompt, onToken, onDone) => {
    const url = `${API_BASE}/infer-stream?prompt=${encodeURIComponent(prompt)}`;
    const es = new EventSource(url);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.done) {
          onDone(data);
          es.close();
        } else {
          onToken(data.token);
        }
      } catch (_err) {
        onDone({ error: "Parse error" });
        es.close();
      }
    };

    es.onerror = () => {
      onDone({ error: "Stream error" });
      es.close();
    };

    return () => es.close();
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
