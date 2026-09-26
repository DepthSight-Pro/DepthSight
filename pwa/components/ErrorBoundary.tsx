// pwa/components/ErrorBoundary.tsx
// Last-resort crash guard: without it any render-time throw unmounts the
// whole app into a black screen (notably painful on phones, where the only
// remedy is killing the app). Shows a recoverable fallback instead.

import React from "react";

interface ErrorBoundaryState {
	error: Error | null;
}

export class ErrorBoundary extends React.Component<
	{ children: React.ReactNode },
	ErrorBoundaryState
> {
	state: ErrorBoundaryState = { error: null };

	static getDerivedStateFromError(error: Error): ErrorBoundaryState {
		return { error };
	}

	componentDidCatch(error: Error, info: React.ErrorInfo): void {
		console.error("[ErrorBoundary] Uncaught render error:", error, info);
	}

	private handleReload = () => {
		window.location.reload();
	};

	private handleResetStorage = () => {
		try {
			// Drop well-known volatile keys that may hold corrupt values,
			// keep the auth token so the user stays logged in.
			for (const key of [
				"appNotifications",
				"autopilot_logs",
				"autopilot_results",
				"autopilot_final_strategy",
				"autopilot_final_kpis",
			]) {
				localStorage.removeItem(key);
			}
		} catch {
			/* ignore */
		}
		window.location.reload();
	};

	render(): React.ReactNode {
		const { error } = this.state;
		if (!error) return this.props.children;

		const ru =
			typeof navigator !== "undefined" &&
			navigator.language.toLowerCase().startsWith("ru");
		return (
			<div
				style={{
					minHeight: "100vh",
					display: "flex",
					flexDirection: "column",
					alignItems: "center",
					justifyContent: "center",
					gap: 12,
					padding: 24,
					background: "#0b0e14",
					color: "#e8ecf3",
					textAlign: "center",
					fontFamily: "system-ui, sans-serif",
				}}
			>
				<div style={{ fontSize: 40 }}>⚠️</div>
				<div style={{ fontSize: 17, fontWeight: 600 }}>
					{ru ? "Что-то пошло не так" : "Something went wrong"}
				</div>
				<div style={{ fontSize: 13, opacity: 0.65, maxWidth: 320 }}>
					{ru
						? "Приложение упало при отрисовке. Перезагрузка обычно помогает."
						: "The app crashed while rendering. Reloading usually helps."}
				</div>
				<button
					type="button"
					onClick={this.handleReload}
					style={{
						marginTop: 8,
						padding: "10px 28px",
						borderRadius: 10,
						border: "none",
						background: "#2563eb",
						color: "#fff",
						fontSize: 15,
						fontWeight: 600,
					}}
				>
					{ru ? "Перезагрузить" : "Reload"}
				</button>
				<button
					type="button"
					onClick={this.handleResetStorage}
					style={{
						padding: "8px 20px",
						borderRadius: 10,
						border: "1px solid #334155",
						background: "transparent",
						color: "#94a3b8",
						fontSize: 13,
					}}
				>
					{ru ? "Сбросить кэш и перезагрузить" : "Reset cache and reload"}
				</button>
			</div>
		);
	}
}
