/**
 * visual_test.js — launches Cognia Desktop visibly, sends a message,
 * waits for the AI response, holds 10 s, then exits.
 *
 * Run: node scripts/visual_test.js
 * Requires: npm install playwright (already a dev dep in cognia_desktop)
 */

const playwrightPath = require.resolve("playwright", {
  paths: [
    require("path").join(__dirname, "..", "cognia_desktop", "node_modules"),
  ],
});
const { _electron: electron } = require(playwrightPath);
const path = require("path");

const APP_DIR   = path.join(__dirname, "..", "cognia_desktop");
const MAIN_JS   = path.join(APP_DIR, "main.js");
const TIMEOUT   = 90_000;   // 90 s max wait for AI response
const HOLD_MS   = 10_000;   // 10 s hold after response

(async () => {
  console.log("[visual_test] Launching Electron app...");

  const app = await electron.launch({
    args: [MAIN_JS],
    cwd: APP_DIR,
    env: {
      ...process.env,
      COGNIA_EXTERNAL_BACKEND: "1",   // don't spawn a second backend
      ELECTRON_ENABLE_LOGGING: "1",
    },
    timeout: 20_000,
  });

  const win = await app.firstWindow();
  await win.waitForLoadState("domcontentloaded");

  console.log("[visual_test] Window open. Waiting for backend-ready badge...");

  // Wait until the badge shows "ready" (or "setup required")
  try {
    await win.waitForSelector("#backend-badge.ready", { timeout: 30_000 });
    console.log("[visual_test] Backend ready. Sending message...");
  } catch (_) {
    console.log("[visual_test] Badge not ready in 30s — trying anyway...");
  }

  // Dismiss privacy modal if visible
  const privacyModal = win.locator("#privacy-modal.visible");
  if (await privacyModal.count() > 0) {
    await win.locator("#btn-privacy-accept").click();
    console.log("[visual_test] Privacy modal dismissed.");
  }

  // Type message and send
  const prompt = win.locator("#prompt");
  await prompt.click();
  await prompt.fill("Hola Cognia, cuéntame algo interesante sobre inteligencia artificial en 2 frases");
  await win.keyboard.press("Enter");
  console.log("[visual_test] Message sent. Waiting 45s for Qwen 7B to generate response (visible on screen)...");

  // The response renders visually in the Electron window even though
  // Playwright cannot detect .bubble.ai mutations from contextBridge callbacks.
  // We wait a fixed time long enough for the 7B model at ~3 tok/s.
  await new Promise(r => setTimeout(r, 45_000));

  console.log(`[visual_test] Holding ${HOLD_MS / 1000}s so you can read the response...`);
  await new Promise(r => setTimeout(r, HOLD_MS));

  console.log("[visual_test] Closing app.");
  await app.close();
  console.log("[visual_test] Done.");
})();
