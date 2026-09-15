const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktopUpdater', {
  check: () => ipcRenderer.invoke('desktop:check-for-updates')
})

contextBridge.exposeInMainWorld('desktopReports', {
  exportMarkdown: payload => ipcRenderer.invoke('desktop:export-report', payload)
})
