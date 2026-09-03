export {}

declare global {
  interface Window {
    desktopUpdater?: {
      check: () => Promise<{status:string; version?:string; message?:string}>
    }
  }
}
