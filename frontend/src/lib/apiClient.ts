// src/lib/apiClient.ts

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

const subscribeTokenRefresh = (cb: (token: string) => void) => {
	refreshSubscribers.push(cb);
};

const onRefreshed = (token: string) => {
	refreshSubscribers.forEach((cb) => cb(token));
	refreshSubscribers = [];
};

export const apiClient = async <T>(
	endpoint: string,
	options: RequestInit = {},
): Promise<T> => {
	const fullUrl = `${API_BASE_URL}${endpoint}`;
	const token = localStorage.getItem("authToken");
	const headers = new Headers(options.headers);
	headers.set("Cache-Control", "no-cache");
	headers.set("Pragma", "no-cache");
	if (!options.body || !(options.body instanceof FormData)) {
		headers.set("Content-Type", "application/json");
	}
	if (token) {
		headers.set("Authorization", `Bearer ${token}`);
	}
	let response = await fetch(fullUrl, { ...options, headers });

	if (
		response.status === 401 &&
		!endpoint.includes("/token") &&
		!endpoint.includes("/refresh")
	) {
		const refreshToken = localStorage.getItem("refreshToken");
		if (refreshToken) {
			if (!isRefreshing) {
				isRefreshing = true;
				try {
					const refreshResponse = await fetch(`${API_BASE_URL}/refresh`, {
						method: "POST",
						headers: {
							"Content-Type": "application/json",
						},
						body: JSON.stringify({ refresh_token: refreshToken }),
					});

					if (refreshResponse.ok) {
						const tokenData = await refreshResponse.json();
						localStorage.setItem("authToken", tokenData.access_token);
						if (tokenData.refresh_token) {
							localStorage.setItem("refreshToken", tokenData.refresh_token);
						}
						onRefreshed(tokenData.access_token);
					} else {
						// Refresh failed
						localStorage.removeItem("authToken");
						localStorage.removeItem("refreshToken");
						localStorage.removeItem("originalAuthToken");
						localStorage.removeItem("originalRefreshToken");
						window.location.href = "/login";
					}
				} catch {
					localStorage.removeItem("authToken");
					localStorage.removeItem("refreshToken");
					window.location.href = "/login";
				} finally {
					isRefreshing = false;
				}
			}

			// Wait for the refresh to complete
			const newAccessToken = await new Promise<string>((resolve) => {
				subscribeTokenRefresh((token: string) => {
					resolve(token);
				});
			});

			// Retry original request with new token
			const retryHeaders = new Headers(options.headers);
			retryHeaders.set("Cache-Control", "no-cache");
			retryHeaders.set("Pragma", "no-cache");
			if (!options.body || !(options.body instanceof FormData)) {
				retryHeaders.set("Content-Type", "application/json");
			}
			retryHeaders.set("Authorization", `Bearer ${newAccessToken}`);
			response = await fetch(fullUrl, { ...options, headers: retryHeaders });
		}
	}

	if (!response.ok) {
		const errorBody = (await response.json().catch(() => ({}))) as Record<
			string,
			string | undefined
		>;
		let message =
			errorBody.detail ||
			errorBody.error ||
			`Request failed with status ${response.status}`;
		if (typeof message !== "string") {
			message = JSON.stringify(message);
		}
		throw new Error(message);
	}
	if (response.status === 204) {
		return undefined as T;
	}
	const parsedResponse = await response.json();
	return parsedResponse &&
		typeof parsedResponse === "object" &&
		"data" in parsedResponse
		? parsedResponse.data
		: parsedResponse;
};
