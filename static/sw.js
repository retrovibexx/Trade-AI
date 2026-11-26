const CACHE = 'trade-ai-v1';
self.addEventListener('install', event => { self.skipWaiting(); });
self.addEventListener('activate', event => { event.waitUntil(self.clients.claim()); });
self.addEventListener('push', event => {
  let data = { title: 'Trade AI signal', body: 'A new signal is available.' };
  try { if (event.data) data = { ...data, ...event.data.json() }; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    tag: data.tag || 'trade-ai-signal',
    data: { url: data.url || '/' },
    icon: '/icon.svg',
    badge: '/icon.svg'
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const client of list) if ('focus' in client) { client.navigate(event.notification.data.url); return client.focus(); }
    return self.clients.openWindow(event.notification.data.url);
  }));
});
