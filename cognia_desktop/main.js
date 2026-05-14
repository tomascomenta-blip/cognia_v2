/**
 * main.js — Cognia Desktop Electron main process
 *
 * 1. Spawns uvicorn cognia_desktop_api:app on port 8765 (Python backend)
 * 2. Polls /health until the server is ready (max 30s)
 * 3. Opens the BrowserWindow with the renderer
 * 4. Forwards IPC calls from renderer → HTTP → Python API
 * 5. Kills the Python process on app quit
 */

const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { autoUpdater } = require("electron-updater");
const { spawn }   = require("child_process");
const path        = require("path");
const http        = require("http");

const API_PORT    = process.env.COGNIA_DESKTOP_PORT || 8765;
const API_BASE    = `http://127.0.0.1:${API_PORT}`;
const POLL_INTERVAL = 500;   // ms between health checks
const POLL_TIMEOUT  = 30000; // ms before giving up

let pythonProc = null;
let mainWindow = null;


// ── Spawn Python backend ───────────────────────────────────────────────

function startBackend() {
  // Resolve cognia_desktop_api.py relative to the app root
  // (works both in dev and in packaged builds via extraResources)
  const appRoot = app.isPackaged
    ? path.join(process.resourcesPath, "cognia_src")
    : path.join(__dirname, "..");

  const apiScript = path.join(appRoot, "cognia_desktop_api.py");
  const python    = process.platform === "win32" ? "python" : "python3";

  pythonProc = spawn(python, [apiScript], {
    cwd: appRoot,
    env: {
      ...process.env,
      COGNIA_DESKTOP_PORT: String(API_PORT),
      COGNIA_PACKAGED:     app.isPackaged ? "1" : "0",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  pythonProc.stdout.on("data", (d) => process.stdout.write(`[API] ${d}`));
  pythonProc.stderr.on("data", (d) => process.stderr.write(`[API] ${d}`));

  pythonProc.on("exit", (code) => {
    if (code !== 0 && mainWindow) {
      mainWindow.webContents.send("backend-error", "Cognia could not start. Please restart the application.");
    }
  });
}

function stopBackend() {
  if (pythonProc) {
    pythonProc.kill("SIGTERM");
    pythonProc = null;
  }
}


// ── Poll until backend ready ───────────────────────────────────────────

function waitForBackend() {
  return new Promise((resolve, reject) => {
    const started = Date.now();

    function check() {
      const req = http.get(`${API_BASE}/ready`, (res) => {
        if (res.statusCode === 200) {
          let raw = "";
          res.on("data", (c) => { raw += c; });
          res.on("end", () => {
            try { resolve(JSON.parse(raw)); }
            catch (_e) { resolve({ status: "ready" }); }
          });
        } else {
          retry();
        }
      });
      req.on("error", retry);
    }

    function retry() {
      if (Date.now() - started > POLL_TIMEOUT) {
        return reject(new Error("Python backend did not start in time."));
      }
      setTimeout(check, POLL_INTERVAL);
    }

    check();
  });
}


// ── Create window ──────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width:  1000,
    height: 700,
    minWidth:  800,
    minHeight: 560,
    title: "Cognia Desktop",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration:  false,
      sandbox: true,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));

  // Open external links in the OS browser, not in Electron
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => { mainWindow = null; });
}


// ── IPC handlers (renderer → Python API) ──────────────────────────────

function apiPost(endpoint, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req  = http.request(
      { hostname: "127.0.0.1", port: API_PORT, path: endpoint,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) } },
      (res) => {
        let raw = "";
        res.on("data", (c) => { raw += c; });
        res.on("end",  () => {
          try { resolve(JSON.parse(raw)); }
          catch (e) { reject(new Error("Invalid JSON from API")); }
        });
      },
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function apiGet(endpoint) {
  return new Promise((resolve, reject) => {
    http.get(`${API_BASE}${endpoint}`, (res) => {
      let raw = "";
      res.on("data", (c) => { raw += c; });
      res.on("end",  () => {
        try { resolve(JSON.parse(raw)); }
        catch (e) { reject(new Error("Invalid JSON from API")); }
      });
    }).on("error", reject);
  });
}

ipcMain.handle("infer",  (_e, prompt) => apiPost("/infer", { prompt }));
ipcMain.handle("route",  (_e, prompt) => apiGet(`/route?prompt=${encodeURIComponent(prompt)}`));
ipcMain.handle("status", ()           => apiGet("/status"));
ipcMain.handle("open-feedback", () => {
  shell.openExternal("https://github.com/tomascomenta-blip/cognia_v2/issues/new");
});


// ── App lifecycle ──────────────────────────────────────────────────────

app.whenReady().then(async () => {
  startBackend();
  createWindow();

  try {
    const readyData = await waitForBackend();
    mainWindow?.webContents.send("backend-ready", readyData);
  } catch (_err) {
    mainWindow?.webContents.send("backend-error", "Cognia could not start. Please restart the application.");
  }

  autoUpdater.checkForUpdatesAndNotify().catch(() => {});

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

autoUpdater.on("update-downloaded", () => {
  mainWindow?.webContents.send("update-available");
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", stopBackend);
