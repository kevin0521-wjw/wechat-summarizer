// 微信消息 AI 助手 —— 前端逻辑（轮询 + 渲染）
let lastTs = 0;           // 消息游标（增量拉取）
let summariesSeq = 0;     // 汇总游标（避免重复渲染）

const KIND_LABEL = { video: '视频', daily: '每日', weekly: '周报', reply: '回复', manual: '手动' };

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

// 首屏
refreshHealth();
refreshStats();
refreshSummaries();
refreshMessages().then(() => { lastTs = lastTs || Math.floor(Date.now() / 1000) - 3600; });

// 轮询
setInterval(refreshHealth, 15000);
setInterval(refreshStats, 10000);
setInterval(refreshSummaries, 10000);
setInterval(refreshMessages, 3000);

// 注册 Service Worker（PWA 离线缓存）
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
