/**
 * electron-builder.config.js
 * ===========================
 * Extended electron-builder configuration for Cognia Desktop.
 *
 * Usage:
 *   electron-builder --config cognia_desktop/electron-builder.config.js
 *   or via scripts/build_release.ps1 / scripts/build_release.sh
 *
 * Code signing:
 *   Windows: set CSC_LINK (pfx path) and CSC_KEY_PASSWORD env vars.
 *   macOS:   set CSC_LINK (p12 path) and CSC_KEY_PASSWORD env vars.
 *   Without signing, builds run but show SmartScreen / Gatekeeper warnings.
 *
 * See docs/INSTALL.md for full build prerequisites.
 */

const path = require("path");

const ROOT = path.join(__dirname, "..");

module.exports = {
  appId: "ai.cognia.desktop",
  productName: "Cognia Desktop",
  copyright: "Cognia Contributors",

  // Output directory relative to this config file
  directories: {
    output: path.join(__dirname, "dist"),
    app:    __dirname,
  },

  // Files bundled into the Electron app package
  files: [
    "main.js",
    "preload.js",
    "renderer/**/*",
    "!renderer/**/*.map",
  ],

  // Python backend and Cognia source shipped as extraResources
  extraResources: [
    {
      from:   ROOT,
      to:     "cognia_src",
      filter: [
        "cognia_desktop_api.py",
        "scripts/cognia_setup.py",
        "shattering/**",
        "coordinator/**",
        "node/**",
        "cognia/**",
        "security/**",
        "requirements.txt",
        "!**/__pycache__/**",
        "!**/*.pyc",
      ],
    },
  ],

  // Windows target: NSIS installer
  win: {
    target:          [{ target: "nsis", arch: ["x64"] }],
    // Sign if env vars present; skip gracefully if not
    signingHashAlgorithms: ["sha256"],
    sign:            process.env.CSC_LINK ? undefined : null,
    artifactName:    "CogniaDesktop-${version}-Setup.${ext}",
  },

  nsis: {
    oneClick:              false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName:          "Cognia Desktop",
    include:               path.join(ROOT, "build", "nsis_check_python.nsh"),
  },

  // macOS target: DMG
  mac: {
    target:       [{ target: "dmg", arch: ["x64", "arm64"] }],
    category:     "public.app-category.productivity",
    artifactName: "CogniaDesktop-${version}.${ext}",
    // Hardened runtime required for notarization
    hardenedRuntime:       true,
    gatekeeperAssess:      false,
    entitlements:          "build/entitlements.mac.plist",
    entitlementsInherit:   "build/entitlements.mac.plist",
  },

  dmg: {
    sign: false,  // DMG signing requires Apple Developer ID
  },

  // Linux target: AppImage
  linux: {
    target:       [{ target: "AppImage", arch: ["x64"] }],
    category:     "Utility",
    artifactName: "CogniaDesktop-${version}.${ext}",
  },

  publish: {
    provider: "github",
    owner:    "tomascomenta-blip",
    repo:     "cognia_v2",
    private:  false,
  },
};
