# Cognia Mobile

Android client for the Cognia AI system. Connects to a local Cognia backend via HTTP.

## Requirements

- Node.js 20+
- Expo CLI: `npm install -g expo-cli`
- EAS CLI (for building APK): `npm install -g eas-cli`
- Cognia backend running on the same network (`cognia_desktop_api.py`)

## Dev

```bash
cd cognia_mobile
npm install
npx expo start
```

Press `a` to launch on Android emulator. The default server URL is `http://10.0.2.2:8765`
(the Android emulator's alias for host machine localhost).

## Build APK

```bash
eas build --platform android --profile preview
```

This produces an `.apk` installable directly on any Android device.
EAS requires a free Expo account: `eas login`.

For a Play Store build (`.aab`):

```bash
eas build --platform android --profile production
```

## Configure server URL

Open the settings screen (tap "config" on the conversation list).

- Emulator: `http://10.0.2.2:8765` (default)
- Real device: `http://<your-PC-LAN-IP>:8765`

Use "probar conexion" to verify the backend is reachable before chatting.

The backend must be started with:

```bash
python cognia_desktop_api.py
```

The app streams tokens as they arrive via SSE (`GET /infer-stream`).
Each AI message shows the sub-model and latency (e.g., `LOGOS · 420ms`).
