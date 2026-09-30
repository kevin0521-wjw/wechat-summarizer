# 微信消息 AI 助手（WeChat Summarizer）

**当前版本：v1.3.1**

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

## 四、环境要求与依赖

### 运行环境

| 项目 | 要求 | 说明 |
|---|---|---|
| **操作系统** | Windows 10/11 | 微信 hook、悬浮窗、Toast 都依赖 Windows |
| **Python** | **3.10 – 3.13** | 实测 3.13.14 可用；3.14 部分包无 wheel |
| **微信** | ⚠️ **见下方「微信版本」这一节** | 这是能否实时监听的关键 |
| **Node.js** | 18+（仅桌面版需要） | 实测 Node 22.22.2 可用 |
| **磁盘** | 约 500 MB | 含可选依赖（隔离 venv 约 100 MB） |
| **内存** | 建议 8 GB+ | 微信本体 + 视频解析比较吃内存 |

### 微信版本（最重要的一条）

| 微信版本 | 实时监听（wcferry） | 开机补读（pywxdump） |
|---|---|---|
| **3.9.x** | ✅ 支持 | ✅ 支持 |
| **4.0 / 4.1.x**（`Weixin.exe`） | ❌ **实测失败**（`wcf.exe 退出码 4`） | ❌ 报 `WeChat No Run` |

> **实测记录（2026-09-30，微信 4.1.15.13）**：
> - `wcferry 39.6.0.0` 能正常 import，但 `Wcf()` 初始化时 **`wcf.exe 退出码 4`** —— 注入失败
> - `pywxdump 3.1.46` 的 `info` 直接报 **`WeChat No Run`**，尽管微信进程（`Weixin.exe`）正在运行
>
> 原因是 WeChatFerry / PyWxDump 主要跟进微信 **3.9.x** 分支，4.x 的进程名与库结构都变了。
> **这是上游限制，不是本项目的 bug。**
>
> **三条可行路径**：
> 1. **降级微信到 3.9.x**（最直接，但会失去 4.x 新功能）
> 2. **等上游适配**（关注 [WeChatFerry releases](https://github.com/lich0821/WeChatFerry/releases)）
> 3. **只用「选中即分析 + 悬浮窗」和「手动粘贴分析」** —— 这部分**完全不依赖微信 hook**，
>    在 4.x 上也能全功能使用（见下方「无 hook 也能用」）

### 无 hook 也能用的功能

微信 4.x 用户仍可完整使用以下能力（不读微信进程，零封号风险）：

| 功能 | 怎么用 |
|---|---|
| **选中即分析**（桌面版） | 微信里选中聊天记录/链接 → `Ctrl+Alt+D` → 悬浮窗出结果 |
| 视频/链接实时解析 | 选中链接按热键，或粘贴到网页版 |
| 聊天记录分析 | 选中后按热键（自动识别为聊天记录类型） |
| 表情包/图片识别 | 复制图片后按热键（需配 `ai.vision_model`） |
| 网页版手动分析 | 打开网页 → 粘贴内容 → 点「分析这段内容」 |
| 历史汇总查看 | 网页版「历史汇总」列表 |

### 安装依赖

```bash
# 1) 核心依赖
pip install -r requirements.txt

# 2) 可选依赖（开机补读微信本地库）—— 装进项目内隔离环境
python scripts/setup_optional.py
```

> ⚠️ **国内网络注意**
> - 清华镜像对 pip 返回 **403**（UA 反爬），换腾讯云：
>   `-i https://mirrors.cloud.tencent.com/pypi/simple`
> - 开着 Clash 等代理会导致 pip 卡住，先 `unset HTTP_PROXY HTTPS_PROXY`。
>
> ⚠️ **依赖冲突（重要的坑）**
> - `wcferry` 的元数据声明 `protobuf==3.10.0`，但它的 pb2 文件需要
>   `google.protobuf.internal.builder`（**protobuf 3.20+ 才有**）→ 装完必须：
>   `pip install "protobuf>=5.29"`
> - `pywxdump` 也会把 protobuf 拖回 3.10.0 → 所以**它必须装到独立环境**。
>   直接 `pip install pywxdump` 会**弄坏 wcferry**。用 `scripts/setup_optional.py`
>   自动处理（它会装进 `vendor/pywxdump_venv/` 并修好主环境 protobuf）。

### 可选依赖会随安装包分发

`vendor/pywxdump_venv/`（约 100 MB）会被 `scripts/build_backend.py` 复制进产物，
再由 electron-builder 的 `extraResources` 塞进安装包。**用户装完即用，无需自己装 pywxdump。**

`core/history_backfill.py` 按以下顺序自动定位 wxdump：

```
① 环境变量 WXDUMP_BIN
② 项目内 vendor/pywxdump_venv/          ← 安装包自带的
③ ~/.workbuddy/binaries/python/envs/wxdump/   ← 本机独立环境
④ PATH 上的 wxdump
```

## 五、快速开始

> 💡 **推荐：先只开「查看界面」验证安装**（不连微信，零风险）
> ```bash
> python web/app.py --no-listener     # 浏览器开 http://127.0.0.1:8080
> ```
> 界面能打开 → 点右上角**「设置」**填 DeepSeek key → 点**「测试连接」**确认通了，
> 环境就没问题，再按下面接真实消息源。

### 1. 配置

> ### 📍 API Key 填在哪里？
>
> **打开网页首页，第一张卡片就是输入框** —— 直接粘贴 key，点「保存 key」，立即生效不用重启。
>
> 具体位置：
> 1. 卡片标题写着「**AI 未配置 · 在这里填 key**」（或「key 还是占位符」），右侧红色「待填写」徽标；
> 2. 下面就是 `API Key *` 输入框（**明文显示**，不是看不清的圆点）+ 绿色「保存 key」按钮；
> 3. 想改模型/推送/群分组，点卡片里的「**更多设置**」，或在右上角「⚙ 设置」里改。
>
> 如果已经配好了，卡片会收起成「**AI 已就绪**」+ 掩码（如 `sk-ab****yz`），不会一直占地方。
>
> 常见误区：配置文件里默认是占位符 `sk-xxxxxxxx`，**它不算已配置** —— 界面会明确提示「key 还是占位符」，必须换成真实 key。

#### 方式 A：网页界面填（推荐，不用碰文件）

**首页直接填**（最快）：见上方「📍 API Key 填在哪里？」。

**更多配置项**在右上角 **「⚙ 设置」** 弹窗里：

| 字段 | 说明 |
|---|---|
| **API Key** | DeepSeek key，**必填**（[申请地址](https://platform.deepseek.com/api_keys)） |
| **Base URL** | 默认 `https://api.deepseek.com/v1`，用中转/其他兼容接口时改这里 |
| **模型** | `deepseek-chat`（快）/ `deepseek-reasoner`（推理强） |
| **视觉模型** | 可选，表情包识别用（DeepSeek 无视觉，可填 `qwen-vl-max` 等） |
| **免打扰/折叠群** | 逗号分隔的群名 → 每周汇总一次 |
| **活跃群** | 逗号分隔的群名（留空则自动取当天消息量 Top 5） |
| **推送通道** | Server酱 / PushPlus / 企微 webhook，选填 |

填完点 **「保存」**，**立即生效、不用重启**。旁边有 **「测试连接」** 按钮，可以先验证 key 通不通再走。

> 🔒 安全设计：保存后只回显掩码（如 `sk-ab****yz`），**明文 key 永远不会再传回浏览器**；
> 输入框留空 = 不修改（防止误清空已填的 key）；只允许写白名单里的键，改不到别的地方。

#### 方式 B：直接编辑 `config.yaml`

不习惯用界面的话，也可以直接改文件（字段含义同上）：

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

### 3. 自检（排查问题时先跑这个）

```bash
# 环境自检：Python/依赖/protobuf/微信版本/wxdump/配置/端口/Node
python scripts/doctor.py

# 网页版全链路自检（需先启动网页版；用 headless Edge，11 项断言）
node tools/smoke-web.mjs

# 设置面板自检（9 项断言）
node tools/verify-settings.mjs
```

## 六、GitHub 上现成项目（借鉴关系）

| 环节 | 借鉴项目 | 用法 |
|------|----------|------|
| 实时监听 | [WeChatFerry](https://github.com/lich0821/WeChatFerry) | 直接 `pip install wcferry` |
| 历史补读 | [WeChatMsg/留痕](https://github.com/LC044/WeChatMsg)（底层 [PyWxDump](https://github.com/xaoyaoo/PyWxDump)） | 解密本地库，补读关机期间消息 |
| 表情/词频 | [Message_Analysis](https://github.com/oorangeeee/Message_Analysis) | 统计算法参考 |
| 视频解析 | [video-link-pipeline](https://github.com/yunqiasen/video-link-pipeline) | 可选后端（`vlp` 命令） |
| 推送 | [push-all-in-one](https://github.com/CaoMeiYouRen/push-all-in-one) / Server酱 / PushPlus | 推送通道 |

## 七、风险与合规（重要）

- **WeChatFerry 依赖微信版本匹配**，微信升级可能失效，需跟进项目 release。
- **个人号自动回复有封号风险**：默认只「出候选不自动发」。
- **PyWxDump 从内存取 key**，要求微信正在运行；仅用于备份自己的数据。
- 所有数据本地处理，`config.yaml` 含 key，**勿提交到公开仓库**（已加 .gitignore 提示）。

## 八、License

MIT

## 九、更新日志

### v1.3.1（2026-09-30）
- **API Key 输入框直接搬到首页**（本次重点）：以前要「点设置 → 在弹窗里找」，现在**打开首页第一张卡就是输入框**，粘贴 key 点「保存 key」即可，一步都不用多点。
  - 卡片随状态自动切换：未配置/占位符 → 展开表单（明文输入框 + 保存 + 测试连接）；已配置 → 收起为掩码显示 + 「更多设置」。
  - 顶部横幅按钮改为「去填 key」，点击**直接平滑滚动并聚焦该输入框**（不再跳设置弹窗）。
- **修复「保存后没反应」的真 bug**：`POST /api/config` 只认「点号扁平键」（`'ai.api_key'`），前端传嵌套对象（`{ai:{api_key}}`）时键名不在白名单，会被**静默忽略**，但接口仍返回 `ok:true` → 界面显示「已保存」，配置其实没动。
  - 后端新增 `_flatten()`，**两种写法都兼容**（嵌套自动拍平）；前端统一改用扁平键。
  - 接口加保护：`written` 为空时返回 **400 + 明确错误**，不再假报成功。
- **修复卡片内两个区块同时显示**：`.ai-setup-form` / `.ai-setup-done` 自身的 `display` 会盖掉 HTML 的 `hidden` 属性，补 `[hidden] { display:none !important }` 强制规则。
- **首页输入框用明文**（`type="text"` 而非 `password`）：占位符 `sk-xxxxxxxx` 能直接看见，不再是看不清的小圆点。
- 新增 `tools/verify-inline-key.mjs`：headless 浏览器验证「打开首页即可填 key」全流程（含**按渲染盒尺寸**判断真实可见，能抓出被 CSS 盖掉的隐藏元素）。
- 版本 1.3.0 → 1.3.1。

### v1.3.0（2026-09-30）
- **修复「找到了设置却不知道要填 key」的根因**：配置文件里默认的占位符 `sk-xxxxxxxx` 被后端 `bool()` 判定为「已配置」，导致首页引导横幅**永远不显示**。
  新增 `core/config.py:is_real_key()` 做语义判断（含 `xxxxxxxx` / `your` / `你的` / `换成` / `example` / `changeme` 等特征或长度 < 12 的都不算真实 key），
  `GET /api/config` 相应拆出三个字段：`api_key_set`（真的是真 key）/ `api_key_present`（有值）/ `api_key_placeholder`（有值但是占位符）。
- **首页三重引导，一眼看到去哪填 key**：
  1. 顶部**吸顶横幅**——区分「完全没填」（红色）与「填的是占位符」（红色 `warn-placeholder` 变体）两种文案；
  2. 新增 **AI 状态卡**（首页第一张卡）：绿点「AI 已就绪」/ 黄点「key 是占位符」/ 红点「还没配 key」，并带一个「配置 AI」按钮；
  3. 右上角「⚙ 设置」按钮（原有）。
- **设置弹窗重新分组，一屏放得下**：① AI 接口（**置顶且默认展开**，带「必填」红标和「如何获取？」链接）② 表情包识别 ③ 群分组 ④ 推送通道 —— 后三组用原生 `<details>` 折叠收纳。
- **修复「保存配置会把注释全删掉」的严重数据损失**：原来用 `yaml.safe_dump` 整体重写，实测把 103 行配置压成 61 行、**32 行中文注释全部清零**。
  改为 `_write_preserving_comments()`：按行读入，用「顶层键 / 二级键」缩进状态机只替换目标那几行，
  注释、空行、注释块一字不动；并且会**继承原有的引号风格**（原本是 `"deepseek-chat"` 就不会变成 `deepseek-chat`），写相同值时为 **0 diff**。
  实测：103 行 → 103 行，整行注释 32 行、行尾注释 17 行全程不变，YAML 仍可正常解析。
- **修复顶栏被吸顶横幅压盖**：`.topbar` 提到 `z-index:20`，`.apikey-banner` 改 `position:sticky; top:69px; z-index:15`，实测两栏无缝衔接（0→77 / 77→160，`overlap:false`）。
- 统计卡片改为整齐 **4 列**：消息总数 / 微信表情 Top / Emoji Top / **覆盖群·联系人数**（`/api/stats` 新增 `rooms` 字段），热词独占全宽一行。
- 「选中即分析」面板标题改「粘贴内容 → AI 分析」，按钮改「读剪贴板并分析」，意图更直白。

### v1.2.1（2026-09-30）
- 新增 `tools/smoke-web.mjs`：网页版全链路冒烟（11 项断言，实测全通过）。
- README「五、快速开始」新增「3. 自检」小节，集中说明三个自检入口。

### v1.2.0（2026-09-30）
- **网页界面可直接填 API Key**：右上角新增「设置」按钮，弹窗里配 DeepSeek key / Base URL / 模型 / 视觉模型 / 群分组 / 推送通道，**保存即生效不用重启**。
- 新增 **「测试连接」** 按钮：填完 key 当场验证通不通，省得猜。
- 未配置 key 时顶部显示提示条，一键跳设置。
- **安全设计**：key 只以掩码回显（`sk-ab****yz`），明文不再传回浏览器；输入框留空 = 不修改；写入走白名单，改不到其他配置键。
- `core/config.py` 新增 `update()` / `mask_key()`，原子写（临时文件 + replace，写崩不坏配置）。
- `core/summarizer.py` 支持热重载配置（保存后无需重启即可用新 key）。
- 新增 `tools/verify-settings.mjs`：headless 浏览器自检设置面板（9 项断言）。
- 新增 `tools/smoke-web.mjs`：网页版全链路冒烟（11 项断言：各接口 + PWA 资源 + 界面区块）。
- README「五、快速开始 → 配置」改为「界面填 / 改文件」两种方式并列。

### v1.1.0（2026-09-29）
- **新增 `scripts/doctor.py` 环境自检**：一条命令查 Python/依赖/protobuf/微信版本/wxdump/配置/端口/Node，末尾给出「你这台机器能用什么」的结论。
- **新增 `scripts/setup_optional.py`**：一键把可选依赖（pywxdump）装进项目内隔离环境 `vendor/pywxdump_venv`，避开 protobuf 版本冲突。
- **可选依赖随安装包分发**：electron-builder `extraResources` 增加 `vendor` 复制项，打包后端时一并带上，用户开箱即用。
- **README 新增「四、环境要求与依赖」**：运行环境表、微信版本对照表、无 hook 也能用的功能表、依赖安装、随包分发说明。
- **requirements.txt 重写**：分「核心 / 桌面端 / 可选」三段，并写明 protobuf 冲突与微信 4.x 限制。
- 版本号统一提升至 1.1.0（desktop/package.json、web/app.py）。

### v1.0.0（2026-09-28）
- 首次发布：CLI / 网页版 / PWA / Electron 桌面版四端架构。
- 「选中 → Ctrl+Alt+D → 悬浮出结果」链路打通（视频/链接/聊天记录/长文字/表情包）。
- 分层汇总：免打扰群每周、活跃群每天、@我实时、视频实时。

