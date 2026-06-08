// pwa/sw.js

const CACHE_NAME = "depthsight-cache-v2";
const urlsToCache = ["/", "/index.html", "/index.css", "/assets/icon.svg"];

// Install event: open cache and add app shell files
self.addEventListener("install", (event) => {
	console.log("[SW] Installing...");
	event.waitUntil(
		caches.open(CACHE_NAME).then((cache) => cache.addAll(urlsToCache)),
	);
});

// Activate event: clean up old caches
self.addEventListener("activate", (event) => {
	console.log("[SW] Activating new service worker...");
	const cacheWhitelist = [CACHE_NAME];
	event.waitUntil(
		caches
			.keys()
			.then((cacheNames) => {
				return Promise.all(
					cacheNames.map((cacheName) => {
						if (cacheWhitelist.indexOf(cacheName) === -1) {
							console.log("[SW] Deleting old cache:", cacheName);
							return caches.delete(cacheName);
						}
					}),
				);
			})
			// --- Adding clients.claim() here. ---
			// When SW is activated (after reload or command), it should immediately
			// take control of all open clients.
			.then(() => self.clients.claim()),
	);
});

// --- Adding listener for command from client ---
self.addEventListener("message", (event) => {
	if (event.data && event.data.type === "SKIP_WAITING") {
		self.skipWaiting();
	}
});

// Fetch event: serve from cache or fetch from network
self.addEventListener("fetch", (event) => {
	const url = new URL(event.request.url);

	// Do not cache API calls or other non-GET requests
	if (
		url.origin !== self.location.origin ||
		event.request.url.includes("/api/v1") ||
		event.request.url.includes("/sw.js") ||
		event.request.method !== "GET"
	) {
		// Let the network handle these requests
		return;
	}

	// Strategy: Network First for navigation requests (HTML pages)
	if (event.request.mode === "navigate") {
		event.respondWith(
			fetch(event.request).catch(() => {
				// If the network fails, fall back to the cache
				return caches.match("/index.html");
			}),
		);
		return;
	}

	// Strategy: Cache First for other assets (JS, CSS, images, etc.)
	event.respondWith(
		caches.match(event.request).then((cachedResponse) => {
			if (cachedResponse) {
				return cachedResponse;
			}
			return fetch(event.request).then((networkResponse) => {
				if (networkResponse && networkResponse.status === 200) {
					const responseToCache = networkResponse.clone();
					caches.open(CACHE_NAME).then((cache) => {
						cache.put(event.request, responseToCache);
					});
				}
				return networkResponse;
			});
		}),
	);
});

// Push event: handle incoming push notifications
self.addEventListener("push", (event) => {
	const data = event.data ? event.data.json() : {};
	const title = data.title || "DepthSight Notification";
	const body = data.body || "You have a new notification from DepthSight.";
	const tag = data.tag || "depthsight-notification"; // Group notifications

	event.waitUntil(
		self.registration.showNotification(title, {
			body: body,
			icon: "/assets/icon.svg", // Path to your app icon
			vibrate: [200, 100, 200],
			tag: tag,
			renotify: true,
		}),
	);
});

// Notification click event: handle user interaction with notifications
self.addEventListener("notificationclick", (event) => {
	event.notification.close();

	event.waitUntil(
		clients
			.matchAll({ type: "window", includeUncontrolled: true })
			.then((clientList) => {
				if (clientList.length > 0) {
					let client = clientList[0];
					for (let i = 0; i < clientList.length; i++) {
						if (clientList[i].focused) {
							client = clientList[i];
						}
					}
					return client.focus();
				}
				return clients.openWindow("/");
			}),
	);
});
