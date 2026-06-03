/**
 * e2e_chat.spec.js
 * Real Electron integration test — launches the app, sends a message,
 * verifies tokens appear in the frontend, and captures console errors.
 *
 * Run: npx playwright test tests/e2e_chat.spec.js --reporter=line
 * Requires: backend running on :8765 (uvicorn cognia_desktop_api:app --port 8765)
 */

const { test, expect } = require("@playwright/test");
const { _electron: electron } = require("playwright");
const path = require("path");

const APP_ROOT = path.join(__dirname, "..");
const BACKEND_URL = "http://127.0.0.1:8765";
const TIMEOUT_FIRST_TOKEN = 60_000; // 60s — first token can be slow (shard load)

async function backendReady() {
  try {
    const r = await fetch(`${BACKEND_URL}/ready`);
    const j = await r.json();
    return j.status === "ready";
  } catch {
    return false;
  }
}

test.describe("Cognia Desktop — chat stream", () => {
  let app;
  let page;
  const consoleErrors = [];
  const consoleWarnings = [];

  test.beforeAll(async () => {
    const ready = await backendReady();
    if (!ready) {
      throw new Error(
        `Backend not running on ${BACKEND_URL}.\n` +
        `Start it with: uvicorn cognia_desktop_api:app --port 8765`
      );
    }
  });

  test.beforeEach(async () => {
    app = await electron.launch({
      args: [APP_ROOT],
      env: {
        ...process.env,
        COGNIA_SETUP_DONE: "1",       // skip setup wizard
        COGNIA_DESKTOP_PORT: "8765",
        COGNIA_EXTERNAL_BACKEND: "1", // use already-running backend, don't spawn new Python
      },
    });

    page = await app.firstWindow();
    await page.waitForLoadState("domcontentloaded");

    // Capture all console output for diagnostics
    page.on("console", (msg) => {
      const text = `[${msg.type()}] ${msg.text()}`;
      if (msg.type() === "error") consoleErrors.push(text);
      if (msg.type() === "warning") consoleWarnings.push(text);
      console.log("RENDERER:", text);
    });

    page.on("pageerror", (err) => {
      consoleErrors.push(`[pageerror] ${err.message}`);
      console.log("RENDERER PAGE ERROR:", err.message);
    });
  });

  test.afterEach(async () => {
    await app.close();
    consoleErrors.length = 0;
    consoleWarnings.length = 0;
  });

  test("backend /ready returns shards:available", async () => {
    const r = await fetch(`${BACKEND_URL}/ready`);
    const j = await r.json();
    expect(j.status).toBe("ready");
    expect(j.inference).toBe("shards");
    console.log("Backend status:", JSON.stringify(j));
  });

  test("SSE stream returns tokens via curl-equivalent fetch", { timeout: 300_000 }, async () => {
    // Warm up shards with a tiny request first so the real test doesn't cold-load
    await fetch(`${BACKEND_URL}/infer-stream?prompt=ok`).then(r => r.body.cancel()).catch(() => {});
    await new Promise(r => setTimeout(r, 2000));

    // Test the SSE endpoint directly from Node (no CORS involved)
    const tokens = [];
    const response = await fetch(
      `${BACKEND_URL}/infer-stream?prompt=${encodeURIComponent("di hola en una palabra")}`
    );
    expect(response.ok).toBe(true);
    expect(response.headers.get("content-type")).toContain("text/event-stream");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let done = false;
    let iterations = 0;

    while (!done && iterations < 200) {
      const { value, done: streamDone } = await reader.read();
      done = streamDone;
      if (value) {
        const chunk = decoder.decode(value);
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data:")) {
            try {
              const data = JSON.parse(line.slice(5).trim());
              if (data.token) tokens.push(data.token);
              if (data.done) { done = true; break; }
            } catch {}
          }
        }
      }
      iterations++;
    }

    console.log("Tokens received from SSE:", tokens);
    console.log("Full text:", tokens.join(""));
    expect(tokens.length).toBeGreaterThan(0);
  });

  test("frontend renders tokens from inferStream after sending message", async () => {
    // Wait for the chat panel to be active and Send button enabled
    const btnSend = page.locator("#btn-send");
    const chatInput = page.locator("#prompt");

    // Wait up to 15s for the backend-ready signal to enable the button
    await expect(btnSend).not.toBeDisabled({ timeout: 15_000 });

    // Type a short prompt
    // Run diagnostic BEFORE sending to avoid competing requests
    const streamDiag = await page.evaluate(async () => {
      return new Promise((resolve) => {
        const url = "http://127.0.0.1:8765/infer-stream?prompt=di+hola";
        const es = new EventSource(url);
        const events = [];
        const timeout = setTimeout(() => {
          es.close();
          resolve({ events, timedOut: true });
        }, 90000);  // 90s — shards are cold on first load

        es.onmessage = (e) => {
          events.push({ type: "message", data: e.data.slice(0, 80) });
          if (events.length >= 3) {
            clearTimeout(timeout);
            es.close();
            resolve({ events, timedOut: false });
          }
        };
        es.onerror = (e) => {
          clearTimeout(timeout);
          es.close();
          resolve({ events, error: "onerror fired", readyState: es.readyState });
        };
      });
    });
    console.log("=== EventSource diagnostic from renderer ===");
    console.log(JSON.stringify(streamDiag, null, 2));

    // Now send the actual message — shards should be warm after the diagnostic request
    await chatInput.fill("di hola");
    await btnSend.click();

    // Wait for at least one AI bubble to appear with text
    const aiBubble = page.locator(".bubble.ai, .system").first();
    await expect(aiBubble).not.toBeEmpty({ timeout: TIMEOUT_FIRST_TOKEN });

    const text = await aiBubble.textContent();
    console.log("AI bubble text:", text);

    // Log any CORS or stream errors captured
    if (consoleErrors.length) {
      console.log("=== CONSOLE ERRORS ===");
      consoleErrors.forEach((e) => console.log(e));
    }

    expect(text.length).toBeGreaterThan(0);
  });

  test("no CORS errors in renderer console", async () => {
    const btnSend = page.locator("#btn-send");
    const chatInput = page.locator("#prompt");

    await expect(btnSend).not.toBeDisabled({ timeout: 15_000 });
    await chatInput.fill("hola");
    await btnSend.click();

    // Wait a few seconds for any CORS errors to surface
    await page.waitForTimeout(8_000);

    const corsErrors = consoleErrors.filter(
      (e) => e.toLowerCase().includes("cors") ||
              e.toLowerCase().includes("access-control") ||
              e.toLowerCase().includes("blocked") ||
              e.toLowerCase().includes("failed to fetch") ||
              e.toLowerCase().includes("eventsource")
    );

    console.log("All console errors:", consoleErrors);
    console.log("CORS-related errors:", corsErrors);

    expect(corsErrors).toHaveLength(0);
  });
});
