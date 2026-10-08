/**
 * 桌面端（打包版）真机自检：真的把 Electron 跑起来，用 CDP 连进渲染进程验证。
 *
 * 为什么需要它 —— 静态检查验不了这些：
 *   - 打包后的 exe 是否真的能起窗口（不是只有 win-unpacked 目录好看）
 *   - 它 spawn 的 backend.exe 是否真的起来了（Electron 套壳 Python 的经典坑）
 *   - app.asar 里的 preload / 页面是否真的渲染出内容
 *
 * 用法：
 *   node tools/desktop-selftest.mjs
 *   PACKAGED_APP=desktop/release/win-unpacked/微信消息AI助手.exe node tools/desktop-selftest.mjs
 *
 * 退出码：0 = 全部通过；1 = 有失败项
 *
 * ⚠️ 两个硬坑（都来自 ~/.workbuddy/skills/electron-app-cdp-verify）：
 *   1) ELECTRON_RUN_AS_NODE 必须清掉 —— WorkBuddy 宿主预设了 =1，
 *      留着它 Electron 会退化成 Node REPL，永远无窗口、且**不报错**（表现就是秒退 exit 0）。
 *   2) NODE_OPTIONS 也要清 —— 宿主的 node-language-shim 会 patch http/https。
 *
 * ⚠️ 需要绕过沙箱运行（要 spawn GUI 进程）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULT_PACKAGED = path.join(
  ROOT, 'desktop', 'release', 'win-unpacked', '微信消息AI助手.exe'
);
const APP = process.env.PACKAGED_APP
  ? path.resolve(process.env.PACKAGED_APP)
  : DEFAULT_PACKAGED;
// 端口都支持环境变量覆盖：默认按 pid 偏移避免撞车，
// 但机器上常驻着别的 Electron 应用（如 space-line），实测仍会撞
// （日志里出现 bind() 0x2740，CDP 连到了别人的窗口，误判成"页面不对"）。
const CDP_PORT = Number(process.env.CDP_PORT) || (9333 + (process.pid % 200));
const BACKEND_PORT = Number(process.env.PORT || 8080);

if (!fs.existsSync(APP)) {
  console.error('❌ 找不到打包产物：' + APP);
  console.error('   先跑：python scripts/build_backend.py && cd desktop && npm run dist');
  process.exit(1);
}

async function waitForPageTarget(port, deadlineMs = 30000) {
  const deadline = Date.now() + deadlineMs;
  while (Date.now() < deadline) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`,
        { signal: AbortSignal.timeout(3000) })).json();
      const pages = list.filter((x) => x.type === 'page' && x.webSocketDebuggerUrl);
      if (pages.length) return pages;
    } catch { /* 端口还没起来 */ }
    await sleep(300);
  }
  throw new Error('CDP 端口 ' + port + ' 上没等到 page target');
}

function connect(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    }
  });
  const ready = new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true });
    ws.addEventListener('error', () => rej(new Error('CDP WebSocket 连接失败')), { once: true });
  });
  const send = (method, params, timeoutMs = 15000) => new Promise((resolve, reject) => {
    const msgId = ++id;
    // 必须带超时：Electron 若在连接后崩溃，未响应的调用会让 Promise 永远挂着
    const timer = setTimeout(() => {
      pending.delete(msgId);
      reject(new Error('CDP 调用超时（' + timeoutMs + 'ms）：' + method));
    }, timeoutMs);
    pending.set(msgId, {
      resolve: (v) => { clearTimeout(timer); resolve(v); },
      reject: (e) => { clearTimeout(timer); reject(e); }
    });
    ws.send(JSON.stringify({ id: msgId, method, params: params || {} }));
  });
  return { ws, ready, send };
}

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
}

let child = null;
let profile = null;
let elLog = '';

try {
  profile = fs.mkdtempSync(path.join(os.tmpdir(), 'wms-desktop-'));

  const env = { ...process.env };
  // ⭐ 这两个是宿主注入的，必须在 spawn 前删掉
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;
  for (const k of ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']) delete env[k];
  env.ELECTRON_ENABLE_LOGGING = '1';
  env.PORT = String(BACKEND_PORT);

  console.log('启动：' + APP);
  child = spawn(APP, [
    '--remote-debugging-port=' + CDP_PORT,
    '--user-data-dir=' + profile,
    // 沙箱/虚拟机里没有可用 GPU，Electron 的 GPU 子进程会反复崩溃并触发
    // "GPU process isn't usable. Goodbye."，主进程以 0x80000003 退出。
    // 用软件渲染绕开。注意别加 --in-process-gpu：那会让渲染进程和 GPU
    // 挤在同一个进程里，CDP 侧表现为 "Target crashed"。
    '--disable-gpu',
    '--disable-gpu-compositing',
    '--disable-software-rasterizer',
    '--disable-dev-shm-usage',
    '--no-sandbox',
  ], { env, stdio: ['ignore', 'pipe', 'pipe'] });

  child.stdout.on('data', (d) => { elLog += d.toString(); });
  child.stderr.on('data', (d) => { elLog += d.toString(); });

  // ---- 1) 后端是否真的起来了（Electron 套壳 Python 的核心断言）----
  let backendOk = false;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    if (child.exitCode !== null) break;
    try {
      const r = await fetch(`http://127.0.0.1:${BACKEND_PORT}/api/health`,
        { signal: AbortSignal.timeout(3000) });
      if (r.ok) { backendOk = true; break; }
    } catch { /* 还没起来 */ }
  }
  check('后端 backend.exe 就绪（/api/health）', backendOk,
        backendOk ? '' : `端口 ${BACKEND_PORT} 30s 内无响应`);

  // ---- 2) 主进程是否还活着（防「孤儿渲染进程」误判）----
  const alive = child.exitCode === null && child.signalCode === null;
  check('Electron 主进程存活', alive,
        alive ? '' : `已退出 code=${child.exitCode} signal=${child.signalCode}`);

  // ---- 3) CDP 是否可达 + 窗口数量 ----
  let pages = [];
  try {
    pages = await waitForPageTarget(CDP_PORT);
    check('CDP 端口可达，有 page target', pages.length > 0, `找到 ${pages.length} 个窗口`);
  } catch (e) {
    check('CDP 端口可达，有 page target', false, String(e.message || e));
  }

  for (const p of pages) {
    console.log(`  · 窗口 title=${JSON.stringify(p.title)} url=${p.url}`);
  }

  // ---- 4) 各个窗口是否真的渲染出内容 ----
  if (pages.length) {
    const probe = `(() => {
      const r = {};
      r.readyState = document.readyState;
      r.title = document.title;
      // ⚠️ 用 textContent 而不是 innerText：innerText 依赖布局，
      //    在没有真实显示器的受限环境里会一律返回空串，导致假失败。
      r.bodyText = document.body ? (document.body.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      r.bodyLen = r.bodyText.length;
      r.htmlLen = document.documentElement ? document.documentElement.outerHTML.length : 0;
      r.buttons = document.querySelectorAll('button').length;
      r.inputs = document.querySelectorAll('input,textarea').length;
      r.apiKeyInput = !!document.getElementById('inl-api-key');
      r.hasDesktopBridge = typeof window.wmsDesktop !== 'undefined'
                        || typeof window.electronAPI !== 'undefined';
      return JSON.stringify(r);
    })()`;
    for (const p of pages) {
      const label = p.title || p.url;
      // 悬浮窗（overlay.html）在没触发分析前是空的、且默认隐藏 —— 不该要求它有正文
      const isOverlay = /overlay\.html/i.test(p.url);
      try {
        const { ws, ready, send } = connect(p.webSocketDebuggerUrl);
        await ready;
        // ⚠️ 关键：CDP target 在**导航提交之前**就出现在 /json/list 里，
        //    此时页面是 about:blank —— readyState 已经是 'complete'，但文档是空的
        //    （outerHTML 恰好 39 字符）。按 readyState 判断会命中假阳性，
        //    必须轮询「文档真的有内容了」再断言。
        let info = null;
        const deadline = Date.now() + 25000;
        while (Date.now() < deadline) {
          const res = await send('Runtime.evaluate', {
            expression: probe, awaitPromise: true, returnByValue: true,
          });
          info = JSON.parse(res.result.value);
          if (info.htmlLen > 100) break;   // 已导航到真实文档
          await sleep(400);
        }
        check(`窗口「${label}」渲染完成`, info.readyState === 'complete',
              `readyState=${info.readyState} htmlLen=${info.htmlLen}`);
        if (isOverlay) {
          check(`窗口「${label}」DOM 就绪（悬浮窗默认空属正常）`,
                info.readyState === 'complete', `bodyLen=${info.bodyLen}`);
        } else {
          check(`窗口「${label}」有实际内容`, info.bodyLen > 0,
                `文本长度=${info.bodyLen} 按钮=${info.buttons} 输入框=${info.inputs}`);
          check(`窗口「${label}」API Key 输入框存在`, info.apiKeyInput,
                info.apiKeyInput ? '' : '未找到 #inl-api-key');
          check(`窗口「${label}」页面标题正确`, /微信/.test(info.title || ''),
                `title=${JSON.stringify(info.title)}`);
        }
        ws.close();   // ⚠️ 只关 WebSocket，绝不调 Browser.close —— 那会关掉整个应用，
                      //    导致后续窗口连不上（第一版就踩了这个坑）
      } catch (e) {
        check(`窗口「${label}」渲染完成`, false, String(e.message || e));
      }
    }
  }

} catch (e) {
  check('自检流程未抛异常', false, String(e.message || e));
} finally {
  if (child && child.exitCode === null) {
    try { child.kill(); } catch { /* ignore */ }
    await sleep(800);
    if (child.exitCode === null) {
      try { process.kill(child.pid, 'SIGKILL'); } catch { /* ignore */ }
    }
  }
  if (profile) { try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ } }
  // Electron 被强杀时它的 before-quit 钩子跑不到，spawn 出来的 backend.exe 会变成孤儿
  // 继续占着端口 —— 下一次自检就会因为端口被占而得到假结果。这里兜底清掉。
  try {
    const { execSync } = await import('node:child_process');
    execSync('taskkill /F /IM backend.exe', { stdio: 'ignore' });
    console.log('（已清理残留 backend.exe）');
  } catch { /* 没有残留，正常 */ }
}

// ---- 输出 ----
console.log('\n===== 桌面端自检结果 =====');
let failed = 0;
for (const r of results) {
  if (!r.ok) failed++;
  console.log(`  ${r.ok ? '✅' : '❌'} ${r.name}${r.detail ? '  — ' + r.detail : ''}`);
}
if (failed && elLog.trim()) {
  console.log('\n----- 应用日志（末 3000 字）-----');
  console.log(elLog.slice(-3000));
}
console.log(`\n通过 ${results.length - failed}/${results.length}`);
process.exit(failed ? 1 : 0);
