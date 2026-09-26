// pwa/services/notificationService.ts

import { readAccessToken } from "./api";

const getAuthToken = (): string | null => readAccessToken();

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

		await postSubscriptionToBackend(pushSubscription.toJSON());

		return pushSubscription;
	};

const postSubscriptionToBackend = async (
	subscription: PushSubscriptionJSON | PushSubscription,
): Promise<void> => {
	// Send subscription to your backend (upsert: heals server-side deletes).
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
		body: JSON.stringify(subscription),
	});
	console.log("Subscribe push response status:", subscribeResponse.status);
	if (!subscribeResponse.ok) {
		const errorBody = await subscribeResponse.json().catch(() => ({}));
		console.error("Failed to send push subscription to backend:", errorBody);
		throw new Error(
			`Failed to send push subscription to backend: ${subscribeResponse.status} ${JSON.stringify(errorBody)}`,
		);
	}
};

export type EnsurePushResult = "active" | "resubscribed" | "unavailable";

/**
 * Self-heal on app launch: re-affirms a live subscription on the backend
 * (heals server-side deletes/overwrites) or recreates a missing one when
 * the user previously enabled notifications. Never prompts out of nowhere:
 * recreation happens only with an already-granted permission.
 */
export const ensurePushSubscription = async (): Promise<EnsurePushResult> => {
	if (
		!("serviceWorker" in navigator) ||
		!("PushManager" in window) ||
		!("Notification" in window)
	) {
		return "unavailable";
	}
	try {
		const registration = await navigator.serviceWorker.ready;
		const existing = await registration.pushManager.getSubscription();
		if (existing) {
			await postSubscriptionToBackend(existing.toJSON());
			return "active";
		}
		if (localStorage.getItem("notificationsEnabled") !== "true") {
			return "unavailable";
		}
		if (Notification.permission !== "granted") {
			if (Notification.permission === "denied") {
				localStorage.setItem("notificationsEnabled", "false");
			}
			return "unavailable";
		}
		await subscribeUserToPush();
		return "resubscribed";
	} catch (err) {
		console.warn("Push self-heal failed:", err);
		return "unavailable";
	}
};

export const sendTestPush = async (): Promise<string> => {
	const token = getAuthToken();
	const headers: HeadersInit = {};
	if (token) {
		headers.Authorization = `Bearer ${token}`;
	}
	const response = await fetch(`/api/v1/notifications/push-test`, {
		method: "POST",
		headers,
	});
	if (response.status === 404) {
		// Backend predates the push-test endpoint: not deployed yet.
		throw new Error("push_test_not_supported");
	}
	if (!response.ok) {
		throw new Error(`Push test failed: ${response.status}`);
	}
	const data = (await response.json()) as { status?: string };
	return data.status ?? "failed";
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
