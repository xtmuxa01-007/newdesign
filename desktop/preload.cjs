const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("tinDesktop", {
  mode: "online",
  updateStatus: () => ipcRenderer.invoke("update-status"),
  checkUpdate: () => ipcRenderer.invoke("update-check"),
  installUpdate: () => ipcRenderer.invoke("update-install"),
});
contextBridge.exposeInMainWorld("tinConnection", {
  info: () => ipcRenderer.invoke("online-info"),
  retry: () => ipcRenderer.invoke("online-retry"),
  retire: () => ipcRenderer.invoke("online-retire"),
});
