const { app, BrowserWindow, dialog } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')

const FRONTEND_HOST = '127.0.0.1'
const FRONTEND_PORT = 5173
const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8000
const BACKEND_HEALTH_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}/health`
const CONTENT_TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
}

let frontendServer
let frontendOwned = false
let backendProcess
let backendOwned = false
let isQuitting = false

app.setPath('userData', path.join(app.getPath('appData'), 'SelfHealNet', 'desktop'))

function runtimeRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, 'app-runtime')
  return path.resolve(__dirname, '..', '..')
}

function pythonExecutable() {
  const candidates = [
    process.env.SELFHEALNET_PYTHON,
    process.env.LOCALAPPDATA &&
      path.join(process.env.LOCALAPPDATA, 'SelfHealNet', 'venv', 'Scripts', 'python.exe'),
    path.join(runtimeRoot(), '.venv', 'Scripts', 'python.exe'),
    path.join(runtimeRoot(), 'venv', 'Scripts', 'python.exe'),
  ].filter(Boolean)

  return candidates.find(candidate => fs.existsSync(candidate))
}

async function backendIsHealthy() {
  try {
    const response = await fetch(BACKEND_HEALTH_URL, { signal: AbortSignal.timeout(1500) })
    if (!response.ok) return false
    const health = await response.json()
    return health.application === 'SelfHealNet' && health.status === 'healthy'
  } catch {
    return false
  }
}

async function waitForBackend(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await backendIsHealthy()) return
    if (backendProcess && backendProcess.exitCode !== null) {
      throw new Error(`The backend stopped during startup (exit code ${backendProcess.exitCode}).`)
    }
    await new Promise(resolve => setTimeout(resolve, 400))
  }
  throw new Error(`The backend did not become healthy within ${timeoutMs / 1000} seconds.`)
}

function startBackend() {
  const python = pythonExecutable()
  if (!python) {
    throw new Error(
      'SelfHealNet Python environment was not found. Install the project backend dependencies, or set SELFHEALNET_PYTHON to your Python executable.'
    )
  }

  const root = runtimeRoot()
  const dataDirectory = path.join(app.getPath('userData'), 'data')
  const logDirectory = path.join(app.getPath('userData'), 'logs')
  fs.mkdirSync(dataDirectory, { recursive: true })
  fs.mkdirSync(logDirectory, { recursive: true })

  const logFile = fs.createWriteStream(path.join(logDirectory, 'backend.log'), { flags: 'a' })
  backendProcess = spawn(
    python,
    ['-m', 'uvicorn', 'backend.main:app', '--host', BACKEND_HOST, '--port', String(BACKEND_PORT)],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [root, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
        DATABASE_URL: `sqlite:///${path.join(dataDirectory, 'selfhealnet.db').replace(/\\/g, '/')}`,
        MODEL_PATH: path.join(root, 'ml', 'model', 'fault_prediction_model.joblib'),
        SDN_CONTROLLER_URL: 'http://127.0.0.1:8080',
        SDN_CONTROLLER_TYPE: 'os_ken_lab',
        SDN_SIMULATION_ENABLED: 'false',
        CORS_ORIGINS: `http://${FRONTEND_HOST}:${FRONTEND_PORT},http://localhost:${FRONTEND_PORT}`,
        API_HOST: BACKEND_HOST,
        API_PORT: String(BACKEND_PORT),
      },
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  )
  backendOwned = true
  backendProcess.stdout.pipe(logFile)
  backendProcess.stderr.pipe(logFile)
  backendProcess.once('error', error => {
    logFile.write(`Failed to start backend: ${error.stack || error.message}\n`)
  })
  backendProcess.once('exit', (code, signal) => {
    logFile.end(`Backend exited (code=${code}, signal=${signal}).\n`)
  })
}

function serveFrontend() {
  const dist = path.join(app.getAppPath(), 'dist')
  const indexFile = path.join(dist, 'index.html')
  if (!fs.existsSync(indexFile)) {
    throw new Error(`The packaged dashboard was not found at ${indexFile}.`)
  }

  frontendServer = http.createServer((request, response) => {
    let requestPath
    try {
      requestPath = decodeURIComponent(new URL(request.url, `http://${FRONTEND_HOST}`).pathname)
    } catch {
      response.writeHead(400).end('Invalid URL')
      return
    }

    const relativePath = requestPath === '/' ? 'index.html' : requestPath.slice(1)
    const resolvedPath = path.resolve(dist, relativePath)
    if (resolvedPath !== dist && !resolvedPath.startsWith(`${dist}${path.sep}`)) {
      response.writeHead(403).end('Forbidden')
      return
    }

    fs.stat(resolvedPath, (statError, stats) => {
      const filePath = !statError && stats.isFile()
        ? resolvedPath
        : path.join(dist, 'index.html')
      fs.readFile(filePath, (readError, contents) => {
        if (readError) {
          response.writeHead(404).end('Not found')
          return
        }
        response.writeHead(200, {
          'Cache-Control': 'no-store',
          'Content-Type': CONTENT_TYPES[path.extname(filePath).toLowerCase()] || 'application/octet-stream',
          'X-Content-Type-Options': 'nosniff',
        })
        response.end(contents)
      })
    })
  })

  return new Promise((resolve, reject) => {
    frontendServer.once('error', async error => {
      if (error.code === 'EADDRINUSE') {
        try {
          const response = await fetch(`http://${FRONTEND_HOST}:${FRONTEND_PORT}`, {
            signal: AbortSignal.timeout(2000),
          })
          const html = await response.text()
          if (response.ok && html.includes('<title>SelfHealNet | Network Operations</title>')) {
            frontendServer = null
            resolve()
            return
          }
        } catch {
          // Report the port conflict below with the same actionable message.
        }
        reject(new Error(
          `Port ${FRONTEND_PORT} is already in use. Close the other service using it, then restart SelfHealNet.`
        ))
        return
      }
      reject(error)
    })
    frontendServer.listen(FRONTEND_PORT, FRONTEND_HOST, () => {
      frontendOwned = true
      resolve()
    })
  })
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 980,
    minHeight: 680,
    title: 'SelfHealNet',
    backgroundColor: '#f0f7ff',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  window.loadURL(`http://${FRONTEND_HOST}:${FRONTEND_PORT}`)
}

function stopOwnedServices() {
  if (frontendOwned && frontendServer) {
    frontendServer.close()
    frontendServer = null
    frontendOwned = false
  }
  if (backendOwned && backendProcess && backendProcess.exitCode === null) {
    backendProcess.kill()
  }
}

app.whenReady().then(async () => {
  try {
    await serveFrontend()
    if (!(await backendIsHealthy())) {
      startBackend()
    }
    await waitForBackend()
    createWindow()
  } catch (error) {
    dialog.showErrorBox('Unable to start SelfHealNet', error.message)
    isQuitting = true
    stopOwnedServices()
    app.quit()
  }
}).catch(error => {
  dialog.showErrorBox('Unable to start SelfHealNet', error.message)
  app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0 && frontendServer) createWindow()
})

app.on('before-quit', event => {
  if (isQuitting) return
  isQuitting = true
  event.preventDefault()
  stopOwnedServices()
  app.quit()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
