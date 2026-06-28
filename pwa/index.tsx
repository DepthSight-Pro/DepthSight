// pwa/index.tsx

import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";
import { AuthProvider } from "./contexts/AuthContext";
import { toast } from "react-hot-toast";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const queryClient = new QueryClient();

const rootElement = document.getElementById("root");
if (!rootElement) {
	throw new Error("Could not find root element to mount to");
}

import { GoogleOAuthProvider } from "@react-oauth/google";

const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

const root = ReactDOM.createRoot(rootElement);
root.render(
	<React.StrictMode>
		<QueryClientProvider client={queryClient}>
			<GoogleOAuthProvider clientId={googleClientId}>
				<AuthProvider>
					<App />
				</AuthProvider>
			</GoogleOAuthProvider>
		</QueryClientProvider>
	</React.StrictMode>,
);

if ("serviceWorker" in navigator) {
	window.addEventListener("load", () => {
		navigator.serviceWorker
			.register("sw.js")
			.then((registration) => {
				console.log("[PWA] ServiceWorker registered");

				// Function to show update notification
				const showUpdateToast = (worker: ServiceWorker) => {
					toast(
						(t) => (
							<div className="flex flex-col gap-2 items-center">
								<span className="text-center font-medium">
									Update available!
								</span>
								<button
									onClick={() => {
										toast.dismiss(t.id);
										// Send command to worker for activation
										worker.postMessage({ type: "SKIP_WAITING" });
									}}
									className="w-full py-2 rounded-md bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-sm"
								>
									Reload
								</button>
							</div>
						),
						{ duration: Infinity },
					); // Notification will not hide automatically
				};

				// 1. Check for updates on load
				registration.update();

				// 2. Listen for 'updatefound' event
				registration.addEventListener("updatefound", () => {
					const newWorker = registration.installing;
					if (newWorker) {
						newWorker.addEventListener("statechange", () => {
							if (
								newWorker.state === "installed" &&
								navigator.serviceWorker.controller
							) {
								showUpdateToast(newWorker);
							}
						});
					}
				});

				let refreshing = false;
				navigator.serviceWorker.addEventListener("controllerchange", () => {
					if (!refreshing) {
						window.location.reload();
						refreshing = true;
					}
				});
			})
			.catch((error) => {
				console.error("[PWA] Service worker registration failed:", error);
			});
	});
}
