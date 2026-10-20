/** Chrome fires `beforeinstallprompt` once, early in the page's life: keep it until the settings page asks. */
export interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>
}

let saved: InstallPromptEvent | null = null
const listeners = new Set<() => void>()

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault()
  saved = e as InstallPromptEvent
  listeners.forEach((fn) => fn())
})
window.addEventListener('appinstalled', () => {
  saved = null
  listeners.forEach((fn) => fn())
})

export function getInstallEvent(): InstallPromptEvent | null {
  return saved
}

export function onInstallChange(fn: () => void): () => void {
  listeners.add(fn)
  return () => void listeners.delete(fn)
}
