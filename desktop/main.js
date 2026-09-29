// Electron 主进程
// ================
// 1) 启动 Python 后端（打包后为 backend.exe，开发时用 python web/app.py）
// 2) 主窗口：加载网页版（历史/统计/配置）
// 3) 悬浮窗：无边框 + 置顶 + 半透明，显示「选中即分析」的结果
// 4) 全局热键（默认 Ctrl+Alt+D）：取选中内容 → 交给 DeepSeek → 浮窗显示
//
// 悬浮窗实现要点（Electron 的坑都在这里）：
//   - 必须 frame:false + transparent:true + alwaysOnTop
//   - 用 setIgnoreMouseEvents 让空白区域可穿透（鼠标能点到下面的窗口）
//   - skipTaskbar 避免占任务栏
//   - 用 'screen' 模块算多显示器下的坐标
const { app, BrowserWindow, globalShortcut, ipcMain, screen, shell, Tray, Menu, nativeImage } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const PORT = Number(process.env.PORT || 8080);
const BASE = `http://127.0.0.1:${PORT}`;

// 受限环境（虚拟机/远程桌面/沙箱）里 GPU 进程可能反复崩溃导致白屏，
// 设 WM_AI_DISABLE_GPU=1 可强制软渲染；命令行 --disable-gpu 同样有效。
if (process.env.WM_AI_DISABLE_GPU === '1' || process.argv.includes('--disable-gpu')) {
  app.disableHardwareAcceleration();
}

let backendProc = null;
let mainWin = null;
let overlayWin = null;
let tray = null;
let hotkey = 'Control+Alt+D';

// ---------------------------------------------------------------------------
// 后端启动
// ---------------------------------------------------------------------------
// 找一个「装了依赖」的 Python：优先环境变量 → 项目 venv → 托管 venv → 系统 python
function findPython() {
  if (process.env.PYTHON && fs.existsSync(process.env.PYTHON)) return process.env.PYTHON;
  const home = process.env.USERPROFILE || process.env.HOME || '';
  const candidates = [
    path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe'),
    path.join(home, '.workbuddy', 'binaries', 'python', 'envs', 'default', 'Scripts', 'python.exe'),
    path.join(__dirname, '..', 'venv', 'Scripts', 'python.exe'),
  ];
  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c;
  }
  return 'python';   // 交给 PATH
}

function backendEntry() {
  const exe = path.join(process.resourcesPath || '', 'backend', 'backend.exe');
  if (fs.existsSync(exe)) {
    return { cmd: exe, args: ['--port', String(PORT), '--host', '127.0.0.1'] };
  }
  const py = findPython();
  const appPy = path.join(__dirname, '..', 'web', 'app.py');
  // 若用了本机 Clash 等代理，Python 侧请求 DeepSeek 会走代理；这里保持干净环境
  const env = { ...process.env };
  delete env.HTTP_PROXY; delete env.HTTPS_PROXY;
  delete env.http_proxy; delete env.https_proxy;
  delete env.ELECTRON_RUN_AS_NODE; delete env.NODE_OPTIONS;   // 防止子进程被 shim 干扰
  return { cmd: py, args: [appPy, '--port', String(PORT), '--host', '127.0.0.1', '--no-listener'], env };
}

function startBackend() {
  const { cmd, args, env } = backendEntry();
  try {
    console.log('[backend] 启动:', cmd);
    backendProc = spawn(cmd, args, { stdio: 'inherit', shell: false, env: env || process.env });
    backendProc.on('error', (e) => console.error('[backend] 启动失败:', e.message));
    backendProc.on('exit', (code) => console.log('[backend] 退出, code =', code));
  } catch (e) {
    console.error('[backend] 无法启动:', e);
  }
}

function waitForBackend(cb, tries = 60) {
  const req = http.get(`${BASE}/api/health`, (res) => { res.resume(); cb(res.statusCode === 200); });
  req.on('error', () => { if (tries-- > 0) setTimeout(() => waitForBackend(cb, tries), 500); else cb(false); });
  req.setTimeout(1000, () => req.destroy());
}

// 简单的后端 POST（避免依赖 node-fetch）
function apiPost(pathname, body) {
  return new Promise((resolve) => {
    const data = Buffer.from(JSON.stringify(body || {}));
    const req = http.request(`${BASE}${pathname}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': data.length },
    }, (res) => {
      let buf = '';
      res.on('data', (c) => (buf += c));
      res.on('end', () => { try { resolve(JSON.parse(buf)); } catch { resolve({ error: buf }); } });
    });
    req.on('error', (e) => resolve({ error: e.message }));
    req.write(data);
    req.end();
  });
}

function apiGet(pathname) {
  return new Promise((resolve) => {
    http.get(`${BASE}${pathname}`, (res) => {
      let buf = '';
      res.on('data', (c) => (buf += c));
      res.on('end', () => { try { resolve(JSON.parse(buf)); } catch { resolve({ error: buf }); } });
    }).on('error', (e) => resolve({ error: e.message }));
  });
}

// ---------------------------------------------------------------------------
// 主窗口
// ---------------------------------------------------------------------------
function createMainWindow() {
  mainWin = new BrowserWindow({
    width: 1120, height: 780, minWidth: 720, minHeight: 560,
    title: '微信消息 AI 助手',
    autoHideMenuBar: true,
    backgroundColor: '#f4f6f5',
    webPreferences: { contextIsolation: true, nodeIntegration: false, preload: path.join(__dirname, 'preload.js') },
  });
  mainWin.loadURL(BASE);
  mainWin.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

// ---------------------------------------------------------------------------
// 悬浮窗：无边框置顶，显示分析结果
// ---------------------------------------------------------------------------
function overlayBounds(sel) {
  const ov = (sel && sel.overlay) || {};
  const w = ov.width || 420;
  const h = ov.height || 560;
  const { workArea } = screen.getPrimaryDisplay();   // 用工作区，避开任务栏
  const pos = ov.position || 'top-right';
  const m = 16;
  const right = workArea.x + workArea.width - w - m;
  const left = workArea.x + m;
  const top = workArea.y + m;
  const bottom = workArea.y + workArea.height - h - m;
  const map = { 'top-right': [right, top], 'top-left': [left, top], 'bottom-right': [right, bottom], 'bottom-left': [left, bottom] };
  const [x, y] = map[pos] || map['top-right'];
  return { x, y, width: w, height: h };
}

function createOverlay(sel) {
  if (overlayWin && !overlayWin.isDestroyed()) return overlayWin;
  const ov = (sel && sel.overlay) || {};
  overlayWin = new BrowserWindow({
    ...overlayBounds(sel),
    frame: false,
    transparent: true,
    resizable: true,
    movable: true,
    skipTaskbar: true,
    show: false,
    alwaysOnTop: true,
    // 'screen-saver' 级别能压住大多数全屏/置顶窗口
    alwaysOnTopLevel: 'screen-saver',
    hasShadow: false,
    opacity: ov.opacity || 0.96,
    webPreferences: { contextIsolation: true, nodeIntegration: false, preload: path.join(__dirname, 'preload.js') },
  });
  overlayWin.loadFile(path.join(__dirname, 'overlay.html'));
  overlayWin.setMenuBarVisibility(false);
  overlayWin.on('closed', () => { overlayWin = null; });
  return overlayWin;
}

function showOverlay(result) {
  const win = createOverlay();
  const send = () => {
    if (win && !win.isDestroyed()) win.webContents.send('overlay:result', result);
    if (win && !win.isDestroyed()) { win.showInactive(); win.setAlwaysOnTop(true, 'screen-saver'); }
  };
  if (win.webContents.isLoading()) win.webContents.once('did-finish-load', send);
  else send();
}

// ---------------------------------------------------------------------------
// 核心：选中 → 分析 → 浮窗
// ---------------------------------------------------------------------------
async function analyzeSelection() {
  // 让浮窗先显示「分析中」，给用户即时反馈
  showOverlay({ kind: 'loading', title: '正在分析…', text: '已取到选中内容，正在请求 DeepSeek…' });
  // 后端通过 ctypes 发 Ctrl+C 取选中文本（Electron 侧不重复实现，保持一致）
  const res = await apiPost('/api/analyze', { use_clipboard: true });
  if (res && res.error) {
    showOverlay({ kind: 'error', title: '分析失败', text: String(res.error) });
    return res;
  }
  showOverlay(res);
  return res;
}

// ---------------------------------------------------------------------------
// 托盘（方便随时唤起/退出）
// ---------------------------------------------------------------------------
function createTray() {
  const icoPath = path.join(__dirname, 'icon.ico');
  let img = fs.existsSync(icoPath) ? nativeImage.createFromPath(icoPath) : nativeImage.createEmpty();
  try {
    tray = new Tray(img);
    tray.setToolTip('微信消息 AI 助手');
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: '打开主界面', click: () => { if (mainWin) { mainWin.show(); mainWin.focus(); } } },
      { label: `选中分析（${hotkey.replace('Control', 'Ctrl')}）`, click: analyzeSelection },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() },
    ]));
    tray.on('double-click', () => { if (mainWin) { mainWin.show(); mainWin.focus(); } });
  } catch (e) {
    console.warn('[tray] 托盘创建失败（忽略）:', e.message);
  }
}

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------
app.whenReady().then(async () => {
  startBackend();

  // 读配置里的热键（后端就绪后）
  waitForBackend(async (ok) => {
    if (!ok) console.error('[backend] 后端未在预期时间内就绪');

    const sel = await apiGet('/api/selection_config');
    if (sel && sel.hotkey) hotkey = normHotkey(sel.hotkey);

    createMainWindow();
    if (!sel || sel.enabled !== false) {
      createOverlay(sel || {});
      const registered = globalShortcut.register(hotkey, analyzeSelection);
      console.log(registered ? `[hotkey] 已注册 ${hotkey}` : `[hotkey] 注册失败（可能被占用）：${hotkey}`);
    }
    createTray();
  });
});

// 'ctrl+alt+d' → 'Control+Alt+D'
function normHotkey(s) {
  return String(s).split('+').map((p) => {
    const t = p.trim().toLowerCase();
    if (t === 'ctrl' || t === 'control') return 'Control';
    if (t === 'alt') return 'Alt';
    if (t === 'shift') return 'Shift';
    if (t === 'win' || t === 'meta' || t === 'super') return 'Super';
    return t.length === 1 ? t.toUpperCase() : t.charAt(0).toUpperCase() + t.slice(1);
  }).join('+');
}

// 渲染进程可主动请求分析（网页版/浮窗里的按钮）
ipcMain.handle('analyze', () => analyzeSelection());
ipcMain.handle('overlay:hide', () => { if (overlayWin && !overlayWin.isDestroyed()) overlayWin.hide(); });
ipcMain.handle('overlay:resize', (_e, h) => {
  if (!overlayWin || overlayWin.isDestroyed()) return;
  const b = overlayWin.getBounds();
  overlayWin.setBounds({ ...b, height: Math.max(120, Math.min(900, Math.round(h))) });
});

app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => {
  if (backendProc) { try { backendProc.kill(); } catch (_) {} }
  app.quit();
});
app.on('before-quit', () => { if (backendProc) { try { backendProc.kill(); } catch (_) {} } });
