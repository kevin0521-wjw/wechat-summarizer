// 微信消息 AI 助手 —— 前端逻辑（轮询 + 渲染）
let lastTs = 0;           // 消息游标（增量拉取）
let summariesSeq = 0;     // 汇总游标（避免重复渲染）

const KIND_LABEL = {
  video: '视频', manual: '手动', reply: '回复',
  daily_all: '每日统计', daily_active: '群日统计', weekly_muted: '每周汇总',
  at_me: '@我',
  selection_text: '选中·文字', selection_chat: '选中·聊天', selection_link: '选中·链接',
  selection_video: '选中·视频', selection_emoji: '选中·表情',
};

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  const p = n => String(n).padStart(2, '0');
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay ? `${p(d.getHours())}:${p(d.getMinutes())}`
                 : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function getJSON(url, opts) {
  try {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) {
    return null;
  }
}

function tag(html) {
  const s = document.createElement('span');
  s.className = 'tag';
  s.innerHTML = html;
  return s;
}

function renderStats(s) {
  if (!s) return;
  document.getElementById('stat-total').textContent = s.total ?? 0;
  const words = s.words || [];
  const wx = s.wx_emoji || [];
  const emo = s.emoji || [];
  const wordsBox = document.getElementById('stat-words');
  wordsBox.innerHTML = '';
  if (words.length) words.forEach(([w, n]) => wordsBox.appendChild(tag(`${w} <b>${n}</b>`)));
  else wordsBox.textContent = '暂无数据';
  const wxBox = document.getElementById('stat-wxemoji');
  wxBox.innerHTML = '';
  if (wx.length) wx.forEach(([e, n]) => wxBox.appendChild(tag(`${e} <b>${n}</b>`)));
  else wxBox.textContent = '暂无数据';
  const emoBox = document.getElementById('stat-emoji');
  emoBox.innerHTML = '';
  if (emo.length) emo.forEach(([e, n]) => emoBox.appendChild(tag(`${e} <b>${n}</b>`)));
  else emoBox.textContent = '暂无数据';
}

function renderMessages(data) {
  if (!data || !data.messages || !data.messages.length) return;
  const feed = document.getElementById('feed');
  if (feed.querySelector('.empty')) feed.innerHTML = '';
  for (const m of data.messages) {
    const li = document.createElement('li');
    const meta = document.createElement('div');
    meta.className = 'meta';
    const who = m.is_self ? '我' : (m.sender || '?').slice(-8);
    const scope = m.is_group ? ' · 群' : '';
    meta.textContent = `${fmtTime(m.ts)}  ${who}${scope}`;
    const body = document.createElement('div');
    body.className = 'body';
    body.textContent = m.content || '[非文本消息]';
    li.appendChild(meta);
    li.appendChild(body);
    feed.prepend(li);
    while (feed.children.length > 60) feed.removeChild(feed.lastChild);
  }
  lastTs = data.now || lastTs;
}

function renderSummaries(list) {
  if (!list || !list.length) return;
  const box = document.getElementById('summaries');
  if (box.querySelector('.empty')) box.innerHTML = '';
  for (const s of list) {
    const li = document.createElement('li');
    const meta = document.createElement('div');
    meta.className = 'meta';
    const k = document.createElement('span');
    k.className = 'kind ' + (s.kind || 'manual');
    k.textContent = KIND_LABEL[s.kind] || s.kind || '汇总';
    meta.appendChild(k);
    meta.appendChild(document.createTextNode(` ${fmtTime(s.ts)}  ${s.title || ''}`));
    const body = document.createElement('div');
    body.className = 'body';
    body.textContent = s.content || '';
    li.appendChild(meta);
    li.appendChild(body);
    box.prepend(li);
    while (box.children.length > 40) box.removeChild(box.lastChild);
  }
}

async function refreshStats() {
  renderStats(await getJSON('/api/stats'));
}
async function refreshMessages() {
  renderMessages(await getJSON(`/api/messages?since=${lastTs}&limit=100`));
}
async function refreshSummaries() {
  renderSummaries(await getJSON('/api/summaries?limit=40'));
}
async function refreshHealth() {
  const h = await getJSON('/api/health');
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-text');
  if (h && h.ok) {
    dot.className = 'dot on';
    txt.textContent = h.listener ? '监听中' : '仅查看模式';
  } else {
    dot.className = 'dot off';
    txt.textContent = '服务未连接';
  }
}

async function triggerSummary(kind) {
  const btn = kind === 'weekly' ? 'btn-weekly' : 'btn-daily';
  const hint = document.getElementById('action-hint');
  document.getElementById(btn).disabled = true;
  hint.textContent = '生成中…';
  const r = await getJSON(`/api/summarize?kind=${kind}`, { method: 'POST' });
  document.getElementById(btn).disabled = false;
  hint.textContent = (r && r.ok) ? '已生成，见「历史汇总」' : '生成失败，请查看后端日志';
  setTimeout(() => { hint.textContent = ''; }, 4000);
  refreshSummaries();
}

document.getElementById('btn-daily').addEventListener('click', () => triggerSummary('daily'));
document.getElementById('btn-weekly').addEventListener('click', () => triggerSummary('weekly'));

// ---------------------------------------------------------------- 选中即分析
const SEL_TAG = {
  video: '视频解析', link: '链接', chat: '聊天记录',
  emoji: '表情包', image: '图片', text: '文字', empty: '无内容', error: '错误'
};

async function analyzeSelection(useClipboard) {
  const box = document.getElementById('analyze-out');
  const hint = document.getElementById('analyze-hint');
  const text = document.getElementById('sel-input').value.trim();
  const kind = document.getElementById('sel-kind').value;

  if (!useClipboard && !text) {
    hint.textContent = '先粘一段内容，或改用「分析剪贴板」';
    setTimeout(() => (hint.textContent = ''), 3000);
    return;
  }

  box.innerHTML = '<div class="loading-line"><span class="mini-spin"></span> 正在请求 DeepSeek…</div>';
  hint.textContent = '';

  const r = await getJSON('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: useClipboard ? null : text,
      hint: kind,
      use_clipboard: !!useClipboard,
    }),
  });

  if (!r) {
    box.innerHTML = '<div class="err">请求失败（后端未启动？）</div>';
    return;
  }
  if (r.error) {
    box.innerHTML = `<div class="err">${r.error}</div>`;
    return;
  }

  const k = r.kind || 'text';
  box.innerHTML =
    `<div class="out-head"><span class="kind ${k}">${SEL_TAG[k] || k}</span>` +
    `<span class="out-title">${(r.title || '').replace(/</g, '&lt;')}</span></div>` +
    `<pre class="out-body">${(r.text || '').replace(/</g, '&lt;')}</pre>`;

  // 桌面版：结果同时推到悬浮窗（若在 Electron 里打开）
  if (window.wxai && window.wxai.onResult) { /* 悬浮窗由主进程推送，这里无需处理 */ }
  refreshSummaries();
}

document.getElementById('btn-analyze').addEventListener('click', () => analyzeSelection(false));
document.getElementById('btn-analyze-clip').addEventListener('click', () => analyzeSelection(true));

// 热键提示（从后端读配置）
(async () => {
  const sc = await getJSON('/api/selection_config');
  if (sc && sc.hotkey) {
    const h = sc.hotkey.replace(/ctrl/gi, 'Ctrl').replace(/alt/gi, 'Alt').toUpperCase();
    const el = document.getElementById('hotkey-hint');
    if (el) el.textContent = `桌面版：选中内容后按 ${h}，结果浮在屏幕上`;
  }
})();

// 首屏
refreshHealth();
refreshStats();
refreshSummaries();
refreshMessages().then(() => { lastTs = lastTs || Math.floor(Date.now() / 1000) - 3600; });
loadConfigState();

// 轮询
setInterval(refreshHealth, 15000);
setInterval(refreshStats, 10000);
setInterval(refreshSummaries, 10000);
setInterval(refreshMessages, 3000);

// 注册 Service Worker（PWA 离线缓存）
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// ---------------------------------------------------------------- 设置面板
const $ = id => document.getElementById(id);

function openSettings() {
  $('settings-mask').hidden = false;
  $('test-result').textContent = '';
  $('test-result').className = 'field-hint';
  loadConfigState();
  $('cfg-api-key').focus();
}
function closeSettings() {
  $('settings-mask').hidden = true;
}

// 读当前配置，把「是否已填」显示出来（key 只回显掩码，不返回明文）
async function loadConfigState() {
  const c = await getJSON('/api/config');
  if (!c) return;

  const set = c.api_key_set;
  const ks = $('key-state');
  if (set) {
    ks.textContent = `已配置（${c.api_key_masked}）· 留空则不修改`;
    ks.className = 'field-hint set';
  } else {
    ks.textContent = '未配置 · 填好后点保存';
    ks.className = 'field-hint';
  }

  // 顶部横幅 + 状态栏提示
  $('apikey-banner').hidden = !!set;

  // 只填充非敏感字段；敏感字段留空（避免覆盖）
  $('cfg-base-url').value = c.base_url || '';
  $('cfg-model').value = c.model || '';
  $('cfg-vision-model').value = c.vision_model || '';
  $('cfg-muted-rooms').value = (c.focus && c.focus.muted_rooms || []).join(', ');
  $('cfg-active-rooms').value = (c.focus && c.focus.active_rooms || []).join(', ');

  // 推送通道状态（用 placeholder 提示已有值）
  const pc = c.push_channels || {};
  $('cfg-serverchan').placeholder = pc.serverchan ? '已配置（留空不修改）' : 'SCTxxxxxxxx';
  $('cfg-pushplus').placeholder = pc.pushplus ? '已配置（留空不修改）' : '选填';
  $('cfg-wecom').placeholder = pc.wecom ? '已配置（留空不修改）' : 'webhook 地址';
}

// 收集要提交的字段（空字符串 = 不修改，后端会跳过）
function collectConfig() {
  const patch = {};
  const put = (key, el) => {
    const v = $(el).value.trim();
    if (v) patch[key] = v;
  };
  put('ai.api_key', 'cfg-api-key');
  put('ai.base_url', 'cfg-base-url');
  put('ai.model', 'cfg-model');
  put('ai.vision_model', 'cfg-vision-model');
  put('focus.muted_rooms', 'cfg-muted-rooms');
  put('focus.active_rooms', 'cfg-active-rooms');
  put('push.serverchan_key', 'cfg-serverchan');
  put('push.pushplus_token', 'cfg-pushplus');
  put('push.wecom_webhook', 'cfg-wecom');
  return patch;
}

async function saveSettings() {
  const st = $('save-state');
  const patch = collectConfig();
  if (!Object.keys(patch).length) {
    st.textContent = '没有要保存的改动';
    st.className = 'save-state';
    setTimeout(() => (st.textContent = ''), 3000);
    return;
  }

  $('settings-save').disabled = true;
  st.textContent = '保存中…';
  st.className = 'save-state';

  const r = await getJSON('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });

  $('settings-save').disabled = false;
  if (r && r.ok) {
    st.textContent = `已保存 ${r.written.length} 项`;
    st.className = 'save-state ok';
    // 清空敏感输入框（避免停留在页面上）
    $('cfg-api-key').value = '';
    $('cfg-serverchan').value = '';
    $('cfg-pushplus').value = '';
    $('cfg-wecom').value = '';
    await loadConfigState();
    setTimeout(() => (st.textContent = ''), 4000);
  } else {
    st.textContent = (r && r.error) ? r.error : '保存失败';
    st.className = 'save-state bad';
  }
}

async function testAI() {
  const out = $('test-result');
  out.textContent = '测试中…';
  out.className = 'field-hint';
  const r = await getJSON('/api/test_ai', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: $('cfg-api-key').value.trim(),   // 留空则用已保存的
      model: $('cfg-model').value.trim(),
      base_url: $('cfg-base-url').value.trim(),
    }),
  });
  if (r && r.ok) {
    out.textContent = `连接正常 · ${r.model} · 模型回复「${r.reply}」`;
    out.className = 'field-hint ok';
  } else {
    out.textContent = (r && r.error) ? r.error : '测试失败';
    out.className = 'field-hint bad';
  }
}

$('btn-settings').addEventListener('click', openSettings);
$('banner-open').addEventListener('click', openSettings);
$('settings-close').addEventListener('click', closeSettings);
$('settings-cancel').addEventListener('click', closeSettings);
$('settings-save').addEventListener('click', saveSettings);
$('btn-test-ai').addEventListener('click', testAI);
$('settings-mask').addEventListener('click', e => {
  if (e.target === $('settings-mask')) closeSettings();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('settings-mask').hidden) closeSettings();
});

// 显示/隐藏 key
$('btn-toggle-key').addEventListener('click', () => {
  const inp = $('cfg-api-key');
  const show = inp.type === 'password';
  inp.type = show ? 'text' : 'password';
  $('btn-toggle-key').textContent = show ? '隐藏' : '显示';
});
