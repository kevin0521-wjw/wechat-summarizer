// Electron 主进程：启动 Python 后端（web/app.py 或打包后的 backend.exe），再加载网页版
const { app, BrowserWindow, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const PORT = Number(process.env.PORT || 8080);
let backendProc = null;

// 解析后端启动方式：优先打包后的 backend.exe，否则本机 python + web/app.py
function backendEntry() {
  const exe = path.join(process.resourcesPath, 'backend', 'backend.exe');
  if (fs.existsSync(exe)) {
    return { cmd: exe, args: ['--port', String(PORT)] };
  }
  const py = process.env.PYTHON || 'python';
  const appPy = path.join(__dirname, '..', 'web', 'app.py');
  return { cmd: py, args: [appPy, '--port', String(PORT), '--no-listener'] };
}

function startBackend() {
  const { cmd, args } = backendEntry();
  try {
    backendProc = spawn(cmd, args, { stdio: 'inherit', shell: false });
    backendProc.on('error', (e) => console.error('[backend] 启动失败:', e.message));
    backendProc.on('exit', (code) => console.log('[backend] 退出, code =', code));
  } catch (e) {
    console.error('[backend] 无法启动:', e);
  }
}

// 轮询等后端就绪
function waitForBackend(cb, tries = 60) {
  const req = http.get(`http://127.0.0.1:${PORT}/api/health`, (res) => {
    res.resume();
    cb(res.statusCode === 200);
  });
  req.on('error', () => {
    if (tries-- > 0) setTimeout(() => waitForBackend(cb, tries), 500);
    else cb(false);
  });
  req.setTimeout(1000, () => req.destroy());
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1120,
    height: 780,
    minWidth: 720,
    minHeight: 560,
    title: '微信消息 AI 助手',
    autoHideMenuBar: true,
    backgroundColor: '#f4f6f5',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.loadURL(`http://127.0.0.1:${PORT}`);
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

app.whenReady().then(() => {
  startBackend();
  waitForBackend((ok) => {
    createWindow();
    if (!ok) console.error('[backend] 后端未在预期时间内就绪，界面可能空白');
  });
});

app.on('window-all-closed', () => {
  if (backendProc) { try { backendProc.kill(); } catch (_) {} }
  app.quit();
});
