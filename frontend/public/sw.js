// Receives receipt files from the system share sheet (Web Share Target) and hands them to the page.
// Nothing else is intercepted or cached: statistics must never be shown stale.
const INBOX = 'share-inbox'

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'POST' || url.pathname !== '/share-target') return
  event.respondWith(receive(event.request))
})

async function receive(request) {
  try {
    const form = await request.formData()
    const cache = await caches.open(INBOX)
    const ids = []
    for (const file of form.getAll('receipt')) {
      if (!(file instanceof File)) continue
      const id = crypto.randomUUID()
      await cache.put(
        `/share-inbox/${id}`,
        new Response(file, {
          headers: {
            'content-type': file.type || 'application/octet-stream',
            'x-file-name': encodeURIComponent(file.name || id),
            'x-saved-at': String(Date.now()),
          },
        }),
      )
      ids.push(id)
    }
    return Response.redirect(`/share?ids=${ids.join(',')}`, 303)
  } catch {
    return Response.redirect('/receipts', 303)
  }
}
