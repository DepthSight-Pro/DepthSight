// pwa/services/notificationService.ts

const getAuthToken = (): string | null => {
	try {
		const tokenData = localStorage.getItem("authToken");
		return tokenData ? JSON.parse(tokenData).access_token : null;
	} catch (e) {
		console.error("Could not parse auth token", e);
		return null;
	}
};

export const getVapidPublicKey = async (): Promise<string> => {
	const token = getAuthToken();
	const headers: HeadersInit = {};
	if (token) {
		headers.Authorization = `Bearer ${token}`;
	}

	console.log("Fetching VAPID public key...");
	const response = await fetch(`/api/v1/notifications/vapid_public_key`, {
		headers,
	});
	console.log("VAPID public key fetch response status:", response.status);
	if (!response.ok) {
		throw new Error("Failed to get VAPID public key");
	}
	const data = await response.json();
	console.log("VAPID public key received:", data.public_key);
	return data.public_key;
};

export const requestNotificationPermission =
	async (): Promise<NotificationPermission> => {
		if (!("Notification" in window)) {
			console.warn("This browser does not support notifications.");
			return "denied";
		}
		const permission = await Notification.requestPermission();
		return permission;
	};

export const subscribeUserToPush =
	async (): Promise<PushSubscription | null> => {
		if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
			console.warn("Push messaging is not supported.");
			return null;
		}

		const permission = await requestNotificationPermission();
		if (permission !== "granted") {
			console.warn("Notification permission not granted.");
			throw new Error("Notification permission not granted.");
		}

		const registration = await navigator.serviceWorker.ready;
		const vapidPublicKey = await getVapidPublicKey();
		const convertedVapidKey = urlBase64ToUint8Array(vapidPublicKey);

		const pushSubscription = await registration.pushManager.subscribe({
			userVisibleOnly: true,
			applicationServerKey: convertedVapidKey,
		});

		// Send subscription to your backend
		const token = getAuthToken();
		const headers: HeadersInit = {
			"Content-Type": "application/json",
		};
		if (token) {
			headers.Authorization = `Bearer ${token}`;
		}

		console.log("Sending push subscription to backend...");
		const subscribeResponse = await fetch(`/api/v1/users/subscribe_push`, {
			method: "POST",
			headers,
			body: JSON.stringify(pushSubscription),
		});
		console.log("Subscribe push response status:", subscribeResponse.status);
		if (!subscribeResponse.ok) {
			const errorBody = await subscribeResponse.json().catch(() => ({}));
			console.error("Failed to send push subscription to backend:", errorBody);
			throw new Error(
				`Failed to send push subscription to backend: ${subscribeResponse.status} ${JSON.stringify(errorBody)}`,
			);
		}

		return pushSubscription;
	};

export const unsubscribeUserFromPush = async (): Promise<boolean> => {
	if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
		console.warn("Push messaging is not supported.");
		return false;
	}

	const registration = await navigator.serviceWorker.ready;
	const subscription = await registration.pushManager.getSubscription();

	if (subscription) {
		const token = getAuthToken();
		const headers: HeadersInit = {
			"Content-Type": "application/json",
		};
		if (token) {
			headers.Authorization = `Bearer ${token}`;
		}

		console.log("Sending push unsubscription to backend...");
		const unsubscribeResponse = await fetch(`/api/v1/users/unsubscribe_push`, {
			method: "POST",
			headers,
			body: JSON.stringify({ endpoint: subscription.endpoint }),
		});
		console.log(
			"Unsubscribe push response status:",
			unsubscribeResponse.status,
		);
		if (!unsubscribeResponse.ok) {
			const errorBody = await unsubscribeResponse.json().catch(() => ({}));
			console.error(
				"Failed to send push unsubscription to backend:",
				errorBody,
			);
			throw new Error(
				`Failed to send push unsubscription to backend: ${unsubscribeResponse.status} ${JSON.stringify(errorBody)}`,
			);
		}
		const successful = await subscription.unsubscribe();
		console.log("Browser push unsubscription successful:", successful);
		return successful;
	}
	return false;
};

const urlBase64ToUint8Array = (base64String: string) => {
	const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
	const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");

	const rawData = window.atob(base64);
	const outputArray = new Uint8Array(rawData.length);

	for (let i = 0; i < rawData.length; ++i) {
		outputArray[i] = rawData.charCodeAt(i);
	}
	return outputArray;
};
