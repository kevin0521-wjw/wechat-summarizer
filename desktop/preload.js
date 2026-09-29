// preload：主窗口与悬浮窗共用（contextIsolation 下暴露有限 API）
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('wxai', {
  // 触发一次「选中分析」
  analyze: () => ipcRenderer.invoke('analyze'),
  // 悬浮窗控制
  hideOverlay: () => ipcRenderer.invoke('overlay:hide'),
  resizeOverlay: (h) => ipcRenderer.invoke('overlay:resize', h),
  // 悬浮窗接收结果
  onResult: (cb) => ipcRenderer.on('overlay:result', (_e, data) => cb(data)),
  isElectron: true,
});
