// 验证：首页能否「一眼看到并在原地填 key」+ 真实保存生效
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = 'http://127.0.0.1:8090/';
const PORT = 9371;

function cleanEnv() {
  const e = { ...process.env };
  for (const k of Object.keys(e)) if (/^(http|https|all|no)_proxy$/i.test(k)) delete e[k];
  return e;
}

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'wms-v-'));
const child = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--window-size=430,1400', '--force-device-scale-factor=2',
  '--user-data-dir=' + profile, '--remote-debugging-port=' + PORT, 'about:blank',
], { detached: true, stdio: 'ignore', env: cleanEnv() });
child.unref();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function findTarget() {
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find((t) => t.type === 'page');
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(500);
  }
  throw new Error('no target');
}

let id = 0;
const ws = new WebSocket(await findTarget());
const pending = new Map();
const jsErrors = [];
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') {
    jsErrors.push((m.params.exceptionDetails?.exception?.description || '').split('\n')[0]);
  }
});
await new Promise((res) => ws.addEventListener('open', res));
const send = (method, params = {}) => new Promise((res) => {
  const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params }));
});
const evalJs = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) return 'ERR: ' + r.result.exceptionDetails.text;
  return r.result?.result?.value;
};

const outDir = path.resolve('output/v130');
fs.mkdirSync(outDir, { recursive: true });
await send('Runtime.enable');
await send('Page.enable');
await send('Page.navigate', { url: BASE + '?t=' + Date.now() });
for (let i = 0; i < 40; i++) {
  await sleep(400);
  if (await evalJs('document.readyState === "complete" && !!document.getElementById("inl-api-key")')) break;
}
await sleep(2500);

console.log('=== A. 打开首页：key 输入框是否「无需任何点击」就可见可填 ===');
const a = await evalJs(`(() => {
  const inp = document.getElementById('inl-api-key');
  const form = document.getElementById('ai-setup-form');
  const done = document.getElementById('ai-setup-done');
  const r = inp.getBoundingClientRect();
  const cs = getComputedStyle(inp);
  // 关键：用「渲染盒尺寸」判断真实可见，而不是只信 hidden 属性
  //（.ai-setup-done 曾因 display:flex 盖掉 hidden，导致两个块同时显示）
  const vis = el => { const b = el.getBoundingClientRect(); const c = getComputedStyle(el);
    return b.width > 0 && b.height > 0 && c.display !== 'none' && c.visibility !== 'hidden'; };
  return JSON.stringify({
    表单展开: !form.hidden,
    表单视觉可见: vis(form),
    完成态视觉可见: vis(done),
    '两者未同时显示': !(vis(form) && vis(done)),
    输入框可见: r.width > 0 && r.height > 0 && cs.display !== 'none',
    输入框尺寸: [Math.round(r.width), Math.round(r.height)],
    首屏可见: r.top < innerHeight && r.bottom > 0,
    输入框位置y: Math.round(r.top),
    可编辑: !inp.disabled && !inp.readOnly,
    type: inp.type,
    标题: document.getElementById('ai-status-title').textContent.trim(),
    徽标: document.getElementById('ai-badge').textContent.trim(),
    保存按钮可见: document.getElementById('inl-save').getBoundingClientRect().width > 0,
    横幅文案: document.getElementById('banner-sub').textContent.trim()
  }, null, 1);
})()`);
console.log(a);

const s1 = await send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: true });
fs.writeFileSync(path.join(outDir, 'A-首页直填.png'), Buffer.from(s1.result.data, 'base64'));

console.log('=== B. 点击横幅「去填 key」→ 是否聚焦输入框 ===');
await evalJs(`document.getElementById('banner-open').click()`);
await sleep(900);
console.log(await evalJs(`JSON.stringify({
  焦点元素: document.activeElement?.id || document.activeElement?.tagName,
  已选中文本: document.activeElement?.selectionStart !== undefined
})`));

console.log('=== C. 真实保存：填入假 key → 是否生效 ===');
const saveResult = await evalJs(`(async () => {
  const inp = document.getElementById('inl-api-key');
  inp.value = 'sk-inline-test-1234567890abcdef';
  document.getElementById('inl-save').click();
  await new Promise(r => setTimeout(r, 2500));
  return JSON.stringify({
    提示: document.getElementById('inl-note').textContent.trim(),
    提示类: document.getElementById('inl-note').className,
    标题: document.getElementById('ai-status-title').textContent.trim(),
    徽标: document.getElementById('ai-badge').textContent.trim(),
    表单已收起: document.getElementById('ai-setup-form').hidden,
    已完成态显示: !document.getElementById('ai-setup-done').hidden,
    掩码: document.getElementById('ai-masked').textContent.trim(),
    横幅已隐藏: document.getElementById('apikey-banner').hidden
  }, null, 1);
})()`);
console.log(saveResult);

const s2 = await send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: true });
fs.writeFileSync(path.join(outDir, 'C-保存后.png'), Buffer.from(s2.result.data, 'base64'));

console.log('=== D. JS 异常检查 ===');
console.log(jsErrors.length ? jsErrors.join('\n') : '无异常 ✓');

console.log('OK → ' + outDir);
ws.close();
try { process.kill(-child.pid); } catch {}
try { process.kill(child.pid); } catch {}
process.exit(0);
