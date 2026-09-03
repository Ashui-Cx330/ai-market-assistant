const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktopUpdater', {
  check: () => ipcRenderer.invoke('desktop:check-for-updates')
})
