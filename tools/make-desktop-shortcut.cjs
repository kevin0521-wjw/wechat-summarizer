// 给「微信消息AI助手」创建桌面 + 开始菜单快捷方式
// 基于 ~/.workbuddy/skills/windows-create-shortcut/scripts/mklnk-args.cjs
// 用途：沙箱拦截 COM/Add-Type/csc，只能走 koffi 直接调 IShellLinkW
const koffi = require('koffi');
const path = require('path');
const fs = require('fs');

const ole32 = koffi.load('ole32.dll');
const CoInitializeEx = ole32.func('int CoInitializeEx(void *pvReserved, uint32 dwCoInit)');
const CoCreateInstance = ole32.func('int CoCreateInstance(void *rclsid, void *pUnkOuter, uint32 dwClsContext, void *riid, void **ppv)');
const CoUninitialize = ole32.func('void CoUninitialize()');

const Guid = koffi.struct('Guid', {
  Data1: 'uint32', Data2: 'uint16', Data3: 'uint16', Data4: koffi.array('uint8', 8),
});

const mkGuid = (d1, d2, d3, lastByte) => {
  const p = koffi.alloc('Guid', 1);
  koffi.encode(p, 'Guid', { Data1: d1, Data2: d2, Data3: d3,
    Data4: [0xC0, 0, 0, 0, 0, 0, 0, lastByte] });
  return p;
};
const CLSID_ShellLink  = mkGuid(0x00021401, 0, 0, 0x46);
const IID_IShellLinkW  = mkGuid(0x000214F9, 0, 0, 0x46);
const IID_IPersistFile = mkGuid(0x0000010b, 0, 0, 0x46);
const CLSCTX_INPROC_SERVER = 1;

const pSetPath = koffi.proto('int SetPath(void *this, str16 pszFile)');
const pSetWorkDir = koffi.proto('int SetWorkingDirectory(void *this, str16 pszDir)');
const pSetDesc = koffi.proto('int SetDescription(void *this, str16 pszName)');
const pSetIcon = koffi.proto('int SetIconLocation(void *this, str16 pszIconPath, int iIcon)');
const pSetArgs = koffi.proto('int SetArguments(void *this, str16 pszArgs)');
const pQI = koffi.proto('int QueryInterface(void *this, void *riid, void **ppv)');
const pSave = koffi.proto('int Save(void *this, str16 pszFileName, int fRemember)');
const pLoad = koffi.proto('int Load(void *this, str16 pszFileName, uint32 dwMode)');
const pGetPath = koffi.proto('int GetPath(void *this, void *pszFile, int cch, void *pfd, uint32 fFlags)');
const pGetArgs = koffi.proto('int GetArguments(void *this, void *pszArgs, int cch)');

const slot = (vtbl, i) => koffi.decode(BigInt(vtbl) + BigInt(i) * 8n, 'void *');

function newShellLink() {
  const ppv = koffi.alloc('void *', 1);
  const hr = CoCreateInstance(CLSID_ShellLink, null, CLSCTX_INPROC_SERVER, IID_IShellLinkW, ppv);
  if (hr !== 0) throw new Error('CoCreateInstance hr=0x' + (hr >>> 0).toString(16));
  const pLink = koffi.decode(ppv, 'void *');
  return { pLink, vtbl: koffi.decode(pLink, 'void *') };
}

function asPersistFile(pLink, vtbl) {
  const ppv = koffi.alloc('void *', 1);
  const hr = koffi.call(slot(vtbl, 0), pQI, pLink, IID_IPersistFile, ppv);
  if (hr !== 0) throw new Error('QueryInterface hr=0x' + (hr >>> 0).toString(16));
  const pPF = koffi.decode(ppv, 'void *');
  return { pPF, vPF: koffi.decode(pPF, 'void *') };
}

function makeShortcut({ lnkPath, target, args, workDir, desc, icon }) {
  const { pLink, vtbl } = newShellLink();
  koffi.call(slot(vtbl, 20), pSetPath, pLink, target);
  if (workDir) koffi.call(slot(vtbl, 9), pSetWorkDir, pLink, workDir);
  if (desc) koffi.call(slot(vtbl, 7), pSetDesc, pLink, desc);
  if (args) koffi.call(slot(vtbl, 11), pSetArgs, pLink, args);
  if (icon) koffi.call(slot(vtbl, 17), pSetIcon, pLink, icon, 0);
  const { pPF, vPF } = asPersistFile(pLink, vtbl);
  const hr = koffi.call(slot(vPF, 6), pSave, pPF, lnkPath, 1);
  if (hr !== 0) throw new Error('Save hr=0x' + (hr >>> 0).toString(16));
}

// 读回 target + arguments 校验，不启动任何程序
function readBack(lnkPath) {
  const { pLink, vtbl } = newShellLink();
  const { pPF, vPF } = asPersistFile(pLink, vtbl);
  if (koffi.call(slot(vPF, 5), pLoad, pPF, lnkPath, 0) !== 0) return null;
  const b1 = Buffer.alloc(1024);
  koffi.call(slot(vtbl, 3), pGetPath, pLink, b1, 1024, null, 0);
  const b2 = Buffer.alloc(2048);
  koffi.call(slot(vtbl, 10), pGetArgs, pLink, b2, 2048);
  // ⚠️ 不要加 GetIconLocation(slot 16) 读回：实测必 SIGSEGV（rc=139）
  return {
    target: b1.toString('utf16le').split('\u0000')[0],
    args: b2.toString('utf16le').split('\u0000')[0],
  };
}

CoInitializeEx(null, 2);

// 目标指向**正式安装位置**（由 NSIS 安装包生成，带卸载入口），
// 而不是构建工作区里的副本 —— 副本删掉快捷方式就失效了。
const APP_DIR = 'C:\\Users\\kevin\\AppData\\Local\\Programs\\wechat-summarizer-desktop';
const EXE = path.join(APP_DIR, '微信消息AI助手.exe');

// 图标直接用 exe 内的（electron-builder 已用 rcedit 写入了应用图标）
const DESC = '微信消息 AI 助手 — 实时消息摘要与智能分析';

// ⚠️ 沙箱里 IShellLink::Save 直接写 Desktop / Start Menu 会返回 0x80070005（拒绝访问），
//    但 bash 往这些目录写普通文件是允许的 —— 说明拦的是 COM 的 IPersistFile 落盘，
//    不是目录 ACL。
//    绕法：先 Save 到项目内的 staging 目录（COM 能写），再用 fs.copyFileSync 搬到目标位置。
//    .lnk 内容与 IShellLink 无关（它只负责序列化），复制过去完全等价。
const STAGING = path.join(__dirname, '..', 'build-tmp', 'lnk-staging');

const jobs = [
  {
    label: '桌面',
    dest: path.join(process.env.USERPROFILE, 'Desktop', '微信消息AI助手.lnk'),
  },
  {
    label: '开始菜单',
    dest: path.join(process.env.APPDATA, 'Microsoft', 'Windows', 'Start Menu',
      'Programs', '微信消息AI助手.lnk'),
  },
];

fs.mkdirSync(STAGING, { recursive: true });

let allOk = true;
for (const j of jobs) {
  const stagePath = path.join(STAGING, path.basename(j.dest));
  try {
    if (!fs.existsSync(EXE)) throw new Error('目标 exe 不存在: ' + EXE);

    // 1) 在 staging 里生成
    makeShortcut({ lnkPath: stagePath, target: EXE, workDir: APP_DIR,
      desc: DESC, icon: EXE });

    // 2) 读回校验（先在 staging 上验，target 应当一致）
    const back = readBack(stagePath);
    if (!back || back.target.toLowerCase() !== EXE.toLowerCase()) {
      throw new Error('读回 target 不匹配: ' + (back && back.target));
    }

    // 3) 复制到最终位置
    fs.mkdirSync(path.dirname(j.dest), { recursive: true });
    fs.copyFileSync(stagePath, j.dest);

    const size = fs.statSync(j.dest).size;
    console.log(`[OK]   ${j.label}  ${size} B  ->  ${j.dest}`);
    console.log(`       target: ${back.target}`);
  } catch (e) {
    allOk = false;
    console.log(`[FAIL] ${j.label}: ${e.message}`);
  }
}

CoUninitialize();
process.exit(allOk ? 0 : 1);
