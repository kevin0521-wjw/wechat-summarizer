// 用 headless Edge + CDP 验证「设置面板」真的能打开、能填、能保存
// 用法: node tools/verify-settings.mjs
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, spawnSync } from 'node:child_process';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const URL_ = process.env.PROBE_URL || 'http://127.0.0.1:8090/';
const PORT = 9337;

function cleanEnv() {
  const e = { ...process.env };
  for (const k of Object.keys(e)) if (/^(http|https|all|no)_proxy$/i.test(k)) delete e[k];
  return e;
}

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'wms-probe-'));
const child = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--user-data-dir=' + profile, '--remote-debugging-port=' + PORT, 'about:blank',
], { detached: true, stdio: 'ignore', env: cleanEnv() });
child.unref();

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function findTarget() {
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find(t => t.type === 'page');
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(500);
  }
  throw new Error('找不到 CDP target');
}

let id = 0;
function makeClient(ws) {
  const pending = new Map();
  ws.addEventListener('message', ev => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  });
  return (method, params = {}) => new Promise((resolve, reject) => {
    const myId = ++id;
    const timer = setTimeout(() => { pending.delete(myId); reject(new Error(method + ' 超时')); }, 20000);
    pending.set(myId, msg => { clearTimeout(timer); resolve(msg.result ?? msg.error); });
    ws.send(JSON.stringify({ id: myId, method, params }));
  });
}

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

(async () => {
  const wsUrl = await findTarget();
  const ws = new WebSocket(wsUrl);
  await new Promise(r => ws.addEventListener('open', r, { once: true }));
  const send = makeClient(ws);

  await send('Page.enable');
  await send('Runtime.enable');
  send('Page.navigate', { url: URL_ });   // 不 await

  // 轮询就绪
  let ready = false;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try {
      const e = await send('Runtime.evaluate', {
        expression: "document.readyState + '|' + (document.getElementById('btn-settings')?1:0)",
        returnByValue: true,
      });
      const v = e?.result?.value || '';
      if (v.startsWith('complete|1')) { ready = true; break; }
    } catch {}
  }
  check('页面加载 + 设置按钮存在', ready);

  const evalJs = async (expr) => {
    const e = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    return e?.result?.value;
  };

  // 1) 面板默认是关的
  const hiddenBefore = await evalJs("document.getElementById('settings-mask').hidden");
  check('初始时设置面板是关闭的', hiddenBefore === true, `hidden=${hiddenBefore}`);

  // 2) 点「设置」按钮 → 打开
  await evalJs("document.getElementById('btn-settings').click()");
  await sleep(600);
  const openAfter = await evalJs("document.getElementById('settings-mask').hidden");
  check('点击「设置」后面板打开', openAfter === false, `hidden=${openAfter}`);

  // 3) 面板里字段齐全
  const fields = await evalJs(`
    JSON.stringify(['cfg-api-key','cfg-base-url','cfg-model','cfg-vision-model',
      'cfg-muted-rooms','cfg-active-rooms','cfg-serverchan','cfg-pushplus','cfg-wecom']
      .filter(id => !document.getElementById(id)))
  `);
  check('9 个配置输入框都存在', fields === '[]', fields === '[]' ? '' : '缺少 ' + fields);

  // 4) 输入框可见且有尺寸（不是被 CSS 藏了）
  const boxes = await evalJs(`
    JSON.stringify(['cfg-api-key','cfg-model'].map(id => {
      const r = document.getElementById(id).getBoundingClientRect();
      return {id, w: Math.round(r.width), h: Math.round(r.height)};
    }))
  `);
  const bl = JSON.parse(boxes || '[]');
  check('输入框真实可见（有宽高）', bl.length === 2 && bl.every(b => b.w > 100 && b.h > 20), boxes);

  // 5) 显示/隐藏 key 切换
  await evalJs("document.getElementById('cfg-api-key').value='sk-abc';document.getElementById('btn-toggle-key').click()");
  const t1 = await evalJs("document.getElementById('cfg-api-key').type + '|' + document.getElementById('btn-toggle-key').textContent");
  check('「显示」能切换 key 明文', t1 === 'text|隐藏', t1);

  // 6) 保存（用空 key 走"不修改"，只改 model，避免污染配置）
  await evalJs(`
    document.getElementById('cfg-api-key').value='';
    document.getElementById('cfg-model').value='deepseek-chat';
    document.getElementById('settings-save').click();
  `);
  await sleep(2500);
  const saveState = await evalJs("document.getElementById('save-state').textContent");
  check('点保存有成功反馈', /已保存/.test(saveState || ''), `save-state="${saveState}"`);

  // 7) Esc 关闭
  await evalJs(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(500);
  const closed = await evalJs("document.getElementById('settings-mask').hidden");
  check('Esc 能关闭面板', closed === true, `hidden=${closed}`);

  // 8) 遮罩层不透明的确认（真实可见性）
  await evalJs("document.getElementById('btn-settings').click()");
  await sleep(400);
  const modalBox = await evalJs(`
    (() => { const r = document.querySelector('.modal').getBoundingClientRect();
      return JSON.stringify({w:Math.round(r.width),h:Math.round(r.height)}); })()
  `);
  const mb = JSON.parse(modalBox || '{}');
  check('设置弹窗有正常尺寸', mb.w > 300 && mb.h > 300, modalBox);

  console.log('\n' + '='.repeat(50));
  const failed = results.filter(r => !r.ok);
  console.log(`结果: ${results.length - failed.length}/${results.length} 通过`);
  if (failed.length) {
    console.log('失败项:');
    failed.forEach(f => console.log('  - ' + f.name + '  ' + f.detail));
  }

  try { await send('Browser.close'); } catch {}
  ws.close();
  spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
  process.exit(failed.length ? 1 : 0);
})().catch(e => {
  console.error('探测失败:', e.message);
  spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
  process.exit(2);
});
