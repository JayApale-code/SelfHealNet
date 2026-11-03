# SelfHealNet Windows Desktop App

The desktop app packages the React dashboard and backend source into a Windows
installer. It opens the dashboard in its own application window, starts the
backend when one is not already healthy, and saves its database and backend log
under the current Windows user's application data directory.

## Requirements

- Windows 10/11 x64.
- The SelfHealNet Python environment at
  `%LOCALAPPDATA%\SelfHealNet\venv\Scripts\python.exe`, with dependencies from
  `backend/requirements.txt` installed.
- WSL2 Ubuntu 22.04, Open vSwitch, OS-Ken, and the Mininet lab for SDN
  functionality. The desktop app does not run elevated commands or ask for a
  sudo password. Start the controller and Mininet lab using the existing VS
  Code tasks before opening the app when SDN lab access is needed.
- Node.js and npm only when building the installer from source.

## Build the Installer

From the project root in PowerShell:

```powershell
Set-Location frontend
npm ci
npm run desktop:dist
```

The installer is written to `frontend/release/SelfHealNet-Setup-0.1.0-x64.exe`.
Install it, then launch **SelfHealNet** from the Start menu or desktop shortcut.

To run the desktop window directly during development:

```powershell
Set-Location frontend
npm run desktop:dev
```

## Runtime Behavior

- The app binds its dashboard to `127.0.0.1:5173` and the backend to
  `127.0.0.1:8000`. These loopback ports must be available when starting the
  application.
- If a healthy SelfHealNet backend is already running on port 8000, the app
  connects to it and leaves that process running when the app closes. Otherwise
  it launches the backend and stops only that process when the app exits.
- The app stores its SQLite database at
  `%APPDATA%\selfhealnet\desktop\data\selfhealnet.db` and its backend log at
  `%APPDATA%\selfhealnet\desktop\logs\backend.log`. These are separate from the
  source project's database and model files.
- The Mininet lab is a separate WSL service. The app does not alter physical
  Wi-Fi/router settings and does not enable generic SDN controller writes.
- To use a different Python executable, set `SELFHEALNET_PYTHON` before
  launching the app.

## Troubleshooting

- If port 5173 is occupied, close the other service and restart the app.
- If the app cannot find Python, install/configure the project Python
  environment or set `SELFHEALNET_PYTHON`.
- Backend startup details are in the desktop app's `logs/backend.log`.
- If SDN status is disconnected, start the existing OS-Ken controller and
  Mininet tasks, then reload the desktop dashboard.
