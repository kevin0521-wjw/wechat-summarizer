# 微信消息 AI 助手（WeChat Summarizer）

电脑微信登录时后台监听消息，AI 实时总结群聊/视频链接，多端推送。一套 Python 后端，四种使用形态：

| 形态 | 说明 | 适合 |
|------|------|------|
| **CLI** | 命令行启动监听，纯后台 | 服务器/挂机 |
| **网页版** | FastAPI + Web 界面（本机或局域网访问） | 电脑上直观查看 |
| **PWA（安卓）** | 手机浏览器打开网页版 →「添加到主屏幕」，像 App 一样用 | 手机看汇总 |
| **桌面版** | Electron 套壳网页版，可打包 exe | 日常主力 |

> ⚠️ 微信分析核心（hook 微信读聊天记录）只能在电脑端做；手机端是「查看电脑端分析结果」的客户端。

---

## 一、架构

```
消息源（WeChatFerry hook / WeFlow API）
   ▼
Engine（core/engine.py：落库 → 路由 → 处理）
   ├─ 视频/链接 ──► video_parser（字幕+评论+tag）──► AI 总结 ──► 推送
   ├─ 免打扰群 ──► 每日定点 AI 汇总 ──► 推送
   ├─ 全部消息 ──► 统计周报（词频/表情）
   └─ 关注私聊 ──► 回复建议（候选，不自动发）
   ▼
推送：Windows Toast / Server酱 / PushPlus / 企微 webhook / txt
   ▼
查看：CLI ｜ Web 界面 ｜ 手机 PWA ｜ 桌面 App
```

## 二、目录结构

```
wechat-summarizer/
├── main.py                 # CLI 入口
├── config.yaml             # 配置（key/频率/推送通道/关注对象）
├── requirements.txt
├── core/                   # 共享后端
│   ├── engine.py           # 核心：监听→落库→路由→处理，CLI/Web 共用
│   ├── message_source.py   # 消息源（WeChatFerry / WeFlow）
│   ├── dispatcher.py       # 路由分类
│   ├── summarizer.py       # DeepSeek 总结/回复建议
│   ├── video_parser.py     # 视频：字幕+评论+tag
│   ├── history_backfill.py # 开机补读本地库（关机期间消息）
│   ├── scheduler.py        # 每日/每周定时汇总
│   ├── pusher.py           # 多通道推送
│   └── stats.py            # 词频/emoji/表情统计
├── db/store.py             # SQLite 落库（消息 + 汇总历史）
├── web/                    # 网页版（= PWA）
│   ├── app.py              # FastAPI 后端
│   └── static/             # 前端（index.html/app.js/style.css/manifest/sw.js/图标）
├── desktop/                # PC 桌面版（Electron 套壳）
│   ├── main.js             # 主进程：起 Python 后端 + 加载网页版
│   ├── package.json        # electron-builder 打包配置
│   └── icon.ico
├── tools/make-icons.py     # 图标生成（SVG → PNG/ICO）
└── scripts/build_backend.py # PyInstaller 把后端打成 backend.exe（可选）
```

## 三、快速开始

### 0. 安装依赖

```bash
pip install -r requirements.txt
```

### 1. 配置

复制 `config.yaml`，填入：
- `ai.api_key`：DeepSeek key
- `push.*`：推送通道（Server酱 / PushPlus / 企微 webhook，至少填一个）
- `focus.contacts`：关注的私聊对象（留空 = 全部）
- `focus.muted_rooms`：免打扰群（这些群走每日汇总）

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

**PC 桌面版（开发模式）**
```bash
cd desktop
npm install
npm start                    # 起 Python 后端 + 打开桌面窗口
```

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
