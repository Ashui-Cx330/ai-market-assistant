export {}

declare global {
  interface Window {
    desktopUpdater?: {
      check: () => Promise<{status:string; version?:string; message?:string}>
    }
    desktopReports?: {
      exportMarkdown: (payload: {filename:string; content:string}) => Promise<{status:string; path?:string}>
    }
  }
}
