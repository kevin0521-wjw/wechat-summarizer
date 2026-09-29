# 微信消息 AI 助手（WeChat Summarizer）

电脑微信登录时后台监听消息，AI 实时总结群聊/视频链接，**选中即分析并悬浮显示**，多端推送。一套 Python 后端，四种使用形态：

| 形态 | 说明 | 适合 |
|------|------|------|
| **CLI** | 命令行启动监听，纯后台 | 服务器/挂机 |
| **网页版** | FastAPI + Web 界面（本机或局域网访问） | 电脑上直观查看 |
| **PWA（安卓）** | 手机浏览器打开网页版 →「添加到主屏幕」，像 App 一样用 | 手机看汇总 |
| **桌面版** | Electron：主窗口 + **悬浮窗** + 全局热键，可打包 exe | 日常主力 |

> ⚠️ 微信分析核心（hook 微信读聊天记录）只能在电脑端做；手机端是「查看电脑端分析结果」的客户端。

---

## ✨ 核心用法：选中 → 热键 → 悬浮出结果

> 这是本项目最爽的功能：**不用切窗口、不用复制粘贴**。

```
在任意地方选中内容 ──► 按 Ctrl+Alt+D ──► 悬浮窗显示 DeepSeek 结果
```

| 你选中的东西 | 系统怎么做 | 输出 |
|---|---|---|
| **视频链接**（B站/抖音/YouTube…） | 秒级解析：下字幕 + 抓评论 + 读 tag | 内容要点 + 观众关注点 |
| **普通链接** | AI 判断指向/价值/风险 | 值不值得点、有无钓鱼风险 |
| **聊天记录**（多行「昵称: 内容」） | 识别为聊天记录 | 主题 + 有没有@我 + 2 条可发回复 |
| **长段文字** | AI 精炼 | 一句话概括 + 要点 + 待办 |
| **表情包 / 图片** | 视觉模型识别（需配 `vision_model`） | 画面/情绪 + 适合什么场合回 |

悬浮窗支持：拖动、收起、复制结果、`Esc` 关闭、内容自适应高度。

---

## 一、汇总频率（分层规则）

| 对象 | 频率 | 说明 |
|---|---|---|
| **视频 / 链接** | **实时（秒级）** | 收到或选中即解析推送 |
| **@我的** | **实时抽出** | 带上下文 + 回复候选 |
| **免打扰 / 折叠群** | **每周一次**（默认周日 21:00） | 消息多又杂，天天推是噪音 |
| **活跃群 / 整体** | **每天出统计**（默认 21:00） | 热词/表情/发言排行 + 链接汇总 |

> 注意这个方向：**免打扰群频率更低（每周），活跃群频率更高（每天）**。配置里改 `schedule.muted_group_weekly` / `schedule.daily_stats`。

## 二、架构

```
消息源（WeChatFerry hook / WeFlow API）
   ▼
Engine（core/engine.py：落库 → 路由 → 处理）
   ├─ 视频/链接 ──► video_parser（字幕+评论+tag）──► AI 总结 ──► 推送（实时）
   ├─ @我的     ──► 抽上下文 ──► 回复候选 ──► 推送（实时）
   ├─ 免打扰群   ──► 每周 AI 汇总 ──► 推送
   ├─ 活跃群/整体 ──► 每天统计（词频/表情/排行）──► 推送
   └─ 关注私聊   ──► 回复建议（候选，不自动发）
   ▼
推送：悬浮窗 / Windows Toast / Server酱 / PushPlus / 企微 webhook / txt
   ▼
选中即分析：任意窗口划词 ──► Ctrl+Alt+D ──► 剪贴板取词 ──► DeepSeek ──► 悬浮窗
   ▼
查看：CLI ｜ Web 界面 ｜ 手机 PWA ｜ 桌面 App（悬浮窗）
```

## 三、目录结构

```
wechat-summarizer/
├── main.py                 # CLI 入口
├── config.yaml             # 配置（key/频率/推送通道/关注对象）
├── requirements.txt
├── core/                   # 共享后端
│   ├── engine.py           # 核心：监听→落库→路由→处理，CLI/Web/桌面共用
│   ├── selection.py        # 选中即分析（剪贴板取词 + 内容分类 + 分发）
│   ├── message_source.py   # 消息源（WeChatFerry / WeFlow）
│   ├── dispatcher.py       # 路由分类
│   ├── summarizer.py       # DeepSeek 总结/回复建议/选中分析
│   ├── video_parser.py     # 视频：字幕+评论+tag
│   ├── history_backfill.py # 开机补读本地库（关机期间消息）
│   ├── scheduler.py        # 分层定时（免打扰群每周 / 活跃群每天）
│   ├── pusher.py           # 多通道推送
│   └── stats.py            # 词频/emoji/表情统计
├── db/store.py             # SQLite 落库（消息 + 汇总历史）
├── web/                    # 网页版（= PWA）
│   ├── app.py              # FastAPI 后端（含 /api/analyze 选中分析）
│   └── static/             # 前端（index/app.js/style.css/manifest/sw.js/图标）
├── desktop/                # PC 桌面版（Electron）
│   ├── main.js             # 主进程：起后端 + 主窗口 + 悬浮窗 + 全局热键
│   ├── preload.js          # 安全桥（contextIsolation 下暴露有限 API）
│   ├── overlay.html        # 悬浮窗界面（无边框+置顶+半透明）
│   ├── package.json        # electron-builder 打包配置
│   └── icon.ico
├── tools/make-icons.py     # 图标生成（SVG → PNG/ICO）
└── scripts/build_backend.py # PyInstaller 把后端打成 backend.exe（可选）
```

## 三、快速开始

> 💡 **推荐：先只开「查看界面」验证安装**（不连微信，零风险）
> ```bash
> python web/app.py --no-listener     # 浏览器开 http://127.0.0.1:8080
> ```
> 界面能打开、能看统计/汇总，说明环境没问题，再按下面接真实消息源。

### 0. 安装依赖

```bash
pip install -r requirements.txt
```

> ⚠️ 国内网络注意：
> - 若 `pip` 从清华镜像报 **403**（UA 反爬），换腾讯云镜像：
>   `pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple`
> - 若开了 Clash 等代理导致 pip 卡住，先 `unset HTTP_PROXY HTTPS_PROXY` 再装。
> - 本机自带代理时，**别把代理写进 pip 配置**，否则 `git credential fill` 会取不到值。

### 1. 配置

复制 `config.yaml`，填入：
- `ai.api_key`：DeepSeek key（必填）
- `ai.vision_model`：**可选**，表情包/图片识别用的多模态模型（DeepSeek 无视觉能力，可填 `qwen-vl-max` / `gpt-4o-mini` 等）
- `push.*`：推送通道（悬浮窗默认开；Server酱 / PushPlus / 企微 webhook 至少填一个用于手机端）
- `focus.muted_rooms`：**免打扰 / 折叠群** → 每周汇总一次
- `focus.active_rooms`：**活跃群** → 每天出统计（留空则自动取当天消息量 top 5）
- `focus.notify_at_me`：`true` 时有人 @我 → 实时抽出推送
- `selection.hotkey`：选中分析热键（默认 `ctrl+alt+d`）

### 2. 各端启动

**CLI（纯后台）**
```bash
python main.py
```

**网页版（含 PWA）**
```bash
python web/app.py            # 浏览器开 http://127.0.0.1:8080
# 手机连同一 Wi-Fi，访问启动时打印的局域网地址
# 「添加到主屏幕」→ 像 App 一样全屏使用
```

**桌面版（含悬浮窗，推荐日常用）**
```bash
cd desktop
npm install
npm start                    # 起后端 + 主窗口 + 悬浮窗 + 注册热键
```
启动后：
1. 在任意窗口**选中**一段内容
2. 按 **Ctrl+Alt+D**
3. 结果浮在屏幕右上角（可拖动/收起/复制/`Esc` 关闭）

> 若报「后端启动失败」，Electron 会依次尝试：`$PYTHON` → `desktop/../.venv` → 托管 venv → 系统 `python`。装了依赖的解释器不在这些位置时，启动命令前加 `PYTHON=/你的/python`。
>
> 虚拟机/远程桌面里若 GPU 崩溃白屏：`npm start -- --disable-gpu` 或设 `WM_AI_DISABLE_GPU=1`。

> 若 Electron 本体下载卡住，先设镜像：
> `export ELECTRON_MIRROR="https://registry.npmmirror.com/-/binary/electron/"`
> （实测本机 3 分钟装完 310 个包，electron v20.18.0）

**PC 桌面版（打包 exe）**
```bash
# 1) 先把 Python 后端打成 exe
pip install pyinstaller
python scripts/build_backend.py          # 产物 backend-dist/backend.exe

# 2) 再打 Electron 安装包
cd desktop
npm run dist                            # 产物 desktop/release/ 下的 exe / NSIS 安装包
```

## 四、GitHub 上现成项目（借鉴关系）

| 环节 | 借鉴项目 | 用法 |
|------|----------|------|
| 实时监听 | [WeChatFerry](https://github.com/lich0821/WeChatFerry) | 直接 `pip install wcferry` |
| 历史补读 | [WeChatMsg/留痕](https://github.com/LC044/WeChatMsg)（底层 [PyWxDump](https://github.com/xaoyaoo/PyWxDump)） | 解密本地库，补读关机期间消息 |
| 表情/词频 | [Message_Analysis](https://github.com/oorangeeee/Message_Analysis) | 统计算法参考 |
| 视频解析 | [video-link-pipeline](https://github.com/yunqiasen/video-link-pipeline) | 可选后端（`vlp` 命令） |
| 推送 | [push-all-in-one](https://github.com/CaoMeiYouRen/push-all-in-one) / Server酱 / PushPlus | 推送通道 |

## 五、风险与合规（重要）

- **WeChatFerry 依赖微信版本匹配**，微信升级可能失效，需跟进项目 release。
- **个人号自动回复有封号风险**：默认只「出候选不自动发」。
- **PyWxDump 从内存取 key**，要求微信正在运行；仅用于备份自己的数据。
- 所有数据本地处理，`config.yaml` 含 key，**勿提交到公开仓库**（已加 .gitignore 提示）。

## 六、License

MIT
