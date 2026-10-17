// Rinkside Service Worker for PWA and Background Push Notifications
const CACHE_NAME = 'rinkside-v2';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

// Background Push Notification handler (wakes up phone & smart watch)
self.addEventListener('push', (event) => {
    let data = {};
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data = { body: event.data.text() };
        }
    }

    const title = data.title || '🏒 Rinkside Alert';
    const options = {
        body: data.body || 'New tournament update available.',
        icon: 'images/icon-192.png',
        badge: 'images/icon-192.png',
        vibrate: [200, 100, 200, 100, 200], // Distinctive hockey double-tap haptic for smart watches
        tag: data.tag || 'rinkside-score-alert',
        renotify: true,
        data: {
            url: data.url || './'
        }
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// When user taps the notification on their phone or watch
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || './';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if (client.url && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
