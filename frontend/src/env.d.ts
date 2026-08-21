/// <reference types="vite/client" />

declare module '@novnc/novnc' {
  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: { credentials?: { password?: string } })
    scaleViewport: boolean
    resizeSession: boolean
    viewOnly: boolean
    qualityLevel: number
    compressionLevel: number
    focus(): void
    disconnect(): void
    sendCredentials(credentials: { password?: string; username?: string }): void
    clipboardPasteFrom(text: string): void
  }
}
