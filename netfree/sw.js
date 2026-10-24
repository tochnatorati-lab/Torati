// Service Worker - שומר גרסה מקומית (cache) של קבצי האפליקציה כדי שתעבוד גם בלי אינטרנט
// לאחר הפעם הראשונה שבה היא נטענה בזמן שהיה חיבור.
const CACHE_NAME = 'torah-app-cache-v10';
const APP_SHELL = [
    './torah_app.html',
    './manifest.json',
    './icon-192.png',
    './bg-library.png',
    './icon-512.png',
    'https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((names) =>
            Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
        )
    );
    self.clients.claim();
});

// אסטרטגיה: קודם מנסים רשת (כדי לקבל תמיד את הגרסה העדכנית של Gemini API וכו'),
// ואם אין רשת - נופלים חזרה לגרסה השמורה, כך שהתוכנה עצמה תמיד תיפתח גם בלי אינטרנט.
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    // בדיקת עדכונים ופקודות השרת המקומי - תמיד ישר לרשת, בלי לשמור במטמון
    const url = event.request.url;
    if (url.includes('/__torati/') || url.includes('version.json')) return;
    event.respondWith(
        fetch(event.request)
            .then((response) => {
                const copy = response.clone();
                caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});
