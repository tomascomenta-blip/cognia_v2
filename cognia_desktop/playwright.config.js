const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 300_000,
  retries: 0,
  reporter: "line",
  use: {
    headless: false,  // show the Electron window so you can see what's happening
  },
});
