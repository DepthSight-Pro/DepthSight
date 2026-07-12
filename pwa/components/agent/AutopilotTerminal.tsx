import type React from "react";
import { useEffect, useRef, useState, useCallback } from "react";
import { Play, Square, Terminal as TerminalIcon, CheckCircle, AlertTriangle, ArrowRight, Activity, TrendingUp, Image as ImageIcon, X } from "lucide-react";
import type { StrategyConfig } from "../../types";
import ReactMarkdown from "react-markdown";

const MAX_IMAGE_DIMENSION = 1000;
const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

type SelectedImage = { base64: string; type: string };

const getImageSrc = (base64: string, mimeType = "image/jpeg") =>
	base64.startsWith("data:") ? base64 : `data:${mimeType};base64,${base64}`;

const processImageFile = (file: File): Promise<SelectedImage> => {
	if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
		return Promise.reject(new Error("Unsupported image type. Use JPEG, PNG, or WebP."));
	}
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onerror = () => reject(new Error("Failed to read image file."));
		reader.onload = () => {
			const image = new Image();
			image.onerror = () => reject(new Error("Failed to decode image file."));
			image.onload = () => {
				const scale = Math.min(1, MAX_IMAGE_DIMENSION / Math.max(image.width, image.height));
				const width = Math.max(1, Math.round(image.width * scale));
				const height = Math.max(1, Math.round(image.height * scale));
				const canvas = document.createElement("canvas");
				canvas.width = width;
				canvas.height = height;
				const ctx = canvas.getContext("2d");
				if (!ctx) { reject(new Error("Canvas not available.")); return; }
				ctx.drawImage(image, 0, 0, width, height);
				const mimeType = file.type === "image/png" ? "image/png" : file.type === "image/webp" ? "image/webp" : "image/jpeg";
				const dataUrl = canvas.toDataURL(mimeType, 0.86);
				const [, rawBase64 = ""] = dataUrl.split(",", 2);
				resolve({ base64: rawBase64, type: mimeType });
			};
			image.src = String(reader.result || "");
		};
		reader.readAsDataURL(file);
	});
};

interface AutopilotTerminalProps {
	onStrategyGenerated: (strategyJson: Partial<StrategyConfig>) => void;
	setIsAutopilotRunning: (running: boolean) => void;
	setActiveIteration: (iteration: number) => void;
}

interface LogEntry {
	id: string;
	timestamp: string;
	type: "info" | "success" | "warn" | "error" | "result";
	message: string;
}

interface IterationResult {
	iteration: number;
	pnl: number;
	win_rate: number;
	trades: number;
	max_dd: number;
	strategy_name: string;
}

export const AutopilotTerminal: React.FC<AutopilotTerminalProps> = ({
	onStrategyGenerated,
	setIsAutopilotRunning,
	setActiveIteration,
}) => {
	const [prompt, setPrompt] = useState(() => {
		return localStorage.getItem("autopilot_prompt") || "Mean-reversion strategy using RSI and Bollinger Bands";
	});
	const [isRunning, setIsRunning] = useState(false);
	const [logs, setLogs] = useState<LogEntry[]>(() => {
		try {
			const saved = localStorage.getItem("autopilot_logs");
			return saved ? JSON.parse(saved) : [];
		} catch (e) {
			return [];
		}
	});
	const [results, setResults] = useState<IterationResult[]>(() => {
		try {
			const saved = localStorage.getItem("autopilot_results");
			return saved ? JSON.parse(saved) : [];
		} catch (e) {
			return [];
		}
	});
	const [currentStatus, setCurrentStatus] = useState<string>("idle");
	const [currentIteration, setCurrentIteration] = useState(0);
	const [finalStrategy, setFinalStrategy] = useState<Partial<StrategyConfig> | null>(() => {
		try {
			const saved = localStorage.getItem("autopilot_final_strategy");
			return saved ? JSON.parse(saved) : null;
		} catch (e) {
			return null;
		}
	});
	const [finalKpis, setFinalKpis] = useState<any | null>(() => {
		try {
			const saved = localStorage.getItem("autopilot_final_kpis");
			return saved ? JSON.parse(saved) : null;
		} catch (e) {
			return null;
		}
	});
	const [maxIterations, setMaxIterations] = useState<number | string>(() => {
		const saved = localStorage.getItem("autopilot_max_iterations");
		return saved ? (isNaN(Number(saved)) ? saved : Number(saved)) : 5;
	});

	useEffect(() => {
		localStorage.setItem("autopilot_prompt", prompt);
	}, [prompt]);

	useEffect(() => {
		localStorage.setItem("autopilot_logs", JSON.stringify(logs));
	}, [logs]);

	useEffect(() => {
		localStorage.setItem("autopilot_results", JSON.stringify(results));
	}, [results]);

	useEffect(() => {
		if (finalStrategy) {
			localStorage.setItem("autopilot_final_strategy", JSON.stringify(finalStrategy));
		} else {
			localStorage.removeItem("autopilot_final_strategy");
		}
	}, [finalStrategy]);

	useEffect(() => {
		if (finalKpis) {
			localStorage.setItem("autopilot_final_kpis", JSON.stringify(finalKpis));
		} else {
			localStorage.removeItem("autopilot_final_kpis");
		}
	}, [finalKpis]);

	useEffect(() => {
		localStorage.setItem("autopilot_max_iterations", String(maxIterations));
	}, [maxIterations]);

	const wsRef = useRef<WebSocket | null>(null);
	const terminalEndRef = useRef<HTMLDivElement>(null);
	const fileInputRef = useRef<HTMLInputElement>(null);

	const [selectedImage, setSelectedImage] = useState<SelectedImage | null>(null);

	const attachImageFile = useCallback(async (file: File) => {
		try {
			if (file.size > 4 * 1024 * 1024) {
				alert("Image is too large. Max size is 4MB.");
				return;
			}
			setSelectedImage(await processImageFile(file));
		} catch (error) {
			alert(error instanceof Error ? error.message : "Could not process image.");
		}
	}, []);

	const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		const file = e.target.files?.[0];
		if (file) {
			if (file.size > 4 * 1024 * 1024) { alert("Image is too large. Max size is 4MB."); return; }
			void attachImageFile(file);
		}
		e.target.value = "";
	};

	const removeSelectedImage = () => setSelectedImage(null);

	// Paste handler for chart screenshots
	useEffect(() => {
		const handlePaste = (e: ClipboardEvent) => {
			const file = e.clipboardData?.files?.[0];
			if (file && ALLOWED_IMAGE_TYPES.has(file.type)) {
				e.preventDefault();
				void attachImageFile(file);
			}
		};
		window.addEventListener("paste", handlePaste);
		return () => window.removeEventListener("paste", handlePaste);
	}, [attachImageFile]);

	useEffect(() => {
		terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
	}, [logs]);

	const addLog = (message: string, type: LogEntry["type"] = "info") => {
		const newLog: LogEntry = {
			id: `${Date.now()}-${Math.random()}`,
			timestamp: new Date().toLocaleTimeString(),
			type,
			message,
		};
		setLogs((prev) => [...prev, newLog]);
	};

	const startAutopilot = () => {
		if (!prompt || isRunning) return;

		setIsRunning(true);
		setIsAutopilotRunning(true);
		setLogs([]);
		setResults([]);
		setFinalStrategy(null);
		setFinalKpis(null);
		setCurrentIteration(0);
		setActiveIteration(0);
		addLog("Initializing Autopilot Agent...", "info");

		const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
		const VITE_WS_URL = import.meta.env.VITE_WS_URL;
		const isDevPort = window.location.port === "3000" || window.location.port === "5173" || window.location.port === "8000";
		
		let baseWsUrl = VITE_WS_URL
			? (window.location.protocol === "https:" ? VITE_WS_URL.replace("ws:", "wss:") : VITE_WS_URL)
			: (isDevPort ? `${wsProtocol}//${window.location.hostname}:8765` : `${wsProtocol}//${window.location.host}`);

		// If it's a relative path starting with /, convert to absolute ws URL
		if (baseWsUrl.startsWith("/")) {
			baseWsUrl = `${wsProtocol}//${window.location.host}${baseWsUrl}`;
		}

		// Ensure it ends with /ws exactly without duplicating /ws/ws
		const WS_URL = baseWsUrl.endsWith("/ws") ? baseWsUrl : `${baseWsUrl}/ws`;

		const authTokenString = localStorage.getItem("authToken");
		let accessToken = "";
		if (authTokenString) {
			const trimmed = authTokenString.trim();
			if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
				try {
					accessToken = JSON.parse(trimmed).access_token || trimmed;
				} catch (e) {
					accessToken = trimmed;
				}
			} else {
				accessToken = trimmed.replace(/^"+|"+$/g, "");
			}
		}

		addLog("Establishing secure WebSocket link...", "info");
		const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(accessToken)}`);
		wsRef.current = ws;

		ws.onopen = () => {
			addLog("Link established. Triggering agent loop...", "success");
			const payload: Record<string, any> = {
				action: "autopilot_run",
				prompt: prompt,
				max_iterations: maxIterations,
			};
			if (selectedImage) {
				payload.image_base64 = selectedImage.base64;
				payload.image_mime_type = selectedImage.type;
			}
			ws.send(JSON.stringify(payload));
		};

		ws.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data);
				if (data.event === "autopilot_status") {
					const { status, message, iteration, pnl, win_rate, trades, max_dd, strategy_name, strategy_json, kpis } = data;
					setCurrentStatus(status);

					if (iteration) {
						setCurrentIteration(iteration);
						setActiveIteration(iteration);
					}

			if (status === "thinking" || status === "validating") {
				addLog(message, "info");
			} else if (status === "loading_data" || status === "generating" || status === "backtesting") {
				addLog(message, "info");
					} else if (status === "candidate_success") {
						addLog(message, "success");
					} else if (status === "failed_iteration") {
						addLog(message, "error");
					} else if (status === "iteration_result") {
						const result: IterationResult = {
							iteration,
							pnl,
							win_rate,
							trades,
							max_dd,
							strategy_name,
						};
						setResults((prev) => [...prev, result]);
						addLog(
							`[Variant ${chr(64 + iteration)}] PnL: ${pnl.toFixed(2)}% | WR: ${win_rate.toFixed(1)}% | Trades: ${trades} | Max DD: ${max_dd.toFixed(1)}%`,
							pnl > 0 ? "success" : "warn",
						);
						if (data.reasoning) {
							addLog(`💡 Model Reasoning: ${data.reasoning}`, "info");
						}
					} else if (status === "success") {
						addLog(`Optimized strategy found in iteration ${iteration}!`, "success");
						addLog(message, "success");
						setFinalStrategy(strategy_json);
						setFinalKpis(kpis);
						stopAutopilot(false);
					} else if (status === "partial_success") {
						addLog(message, "warn");
						setFinalStrategy(strategy_json);
						setFinalKpis(kpis);
						stopAutopilot(false);
					} else if (status === "error") {
						addLog(`Error: ${message}`, "error");
						stopAutopilot(true);
					}
				}
			} catch (e) {
				console.error("Failed to parse websocket message", e);
			}
		};

		ws.onerror = (err) => {
			addLog("Connection link error.", "error");
			stopAutopilot(true);
		};

		ws.onclose = () => {
			addLog("Connection closed.", "info");
			setIsRunning(false);
			setIsAutopilotRunning(false);
		};
	};

	const stopAutopilot = (hasError = false) => {
		if (wsRef.current) {
			wsRef.current.close();
		}
		setIsRunning(false);
		setIsAutopilotRunning(false);
		setCurrentStatus("idle");
		if (hasError) {
			addLog("Autopilot run aborted due to error.", "error");
		} else {
			addLog("Autopilot run completed.", "success");
		}
	};

	const chr = (code: number) => String.fromCharCode(code);

	return (
		<div className="flex flex-col h-full bg-card border border-border rounded-2xl overflow-hidden shadow-2xl p-3 sm:p-4">
			{/* Input Header */}
			<div className="mb-4 border-b border-border pb-4">
				<div className="flex flex-col">
					<label className="text-[10px] uppercase font-mono text-muted-foreground mb-1.5" htmlFor="prompt-input">Agent Instructions</label>
					<div className="flex flex-col sm:flex-row gap-2">
						<div className="flex w-full sm:flex-1 gap-2">
							<input
								id="prompt-input"
								type="text"
								value={prompt}
								onChange={(e) => setPrompt(e.target.value)}
								disabled={isRunning}
								placeholder="Describe desired behavior..."
								className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary disabled:opacity-50 transition min-w-0"
							/>
							<input
								type="file"
								accept="image/*"
								className="hidden"
								ref={fileInputRef}
								onChange={handleFileChange}
							/>
							<button
								onClick={() => fileInputRef.current?.click()}
								disabled={isRunning}
								className="shrink-0 bg-background border border-border rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground hover:border-primary transition disabled:opacity-50"
								type="button"
								title="Attach chart screenshot"
							>
								<ImageIcon className="w-4 h-4" />
							</button>
						</div>
						<div className="flex w-full sm:w-auto gap-2">
							<select
								value={maxIterations}
								onChange={(e) => {
									const val = e.target.value;
									setMaxIterations(isNaN(Number(val)) ? val : Number(val));
								}}
								disabled={isRunning}
								className="flex-1 sm:flex-none bg-background border border-border rounded-lg px-2 py-2 text-xs text-foreground focus:outline-none focus:border-primary disabled:opacity-50 transition cursor-pointer font-sans"
							>
								<option value={5}>5 runs</option>
								<option value={10}>10 runs</option>
								<option value={20}>20 runs</option>
								<option value="until_profitable">Until Profit</option>
							</select>
							{isRunning ? (
								<button
									onClick={() => stopAutopilot(false)}
									className="flex-1 sm:flex-none justify-center bg-destructive hover:bg-destructive/90 text-white rounded-lg px-4 flex items-center gap-1.5 text-sm font-medium transition shrink-0"
									type="button"
								>
									<Square className="w-4 h-4 fill-white" /> Stop
								</button>
							) : (
								<button
									onClick={startAutopilot}
									disabled={!prompt}
									className="flex-1 sm:flex-none justify-center bg-primary hover:bg-primary/90 disabled:bg-indigo-800/40 text-white rounded-lg px-4 flex items-center gap-1.5 text-sm font-medium transition disabled:opacity-50 shrink-0"
									type="button"
								>
									<Play className="w-4 h-4 fill-white" /> Optimize
								</button>
							)}
						</div>
					</div>
				</div>
			</div>

			{/* Image Preview */}
			{selectedImage && (
				<div className="mb-3 border border-border rounded-xl p-2 bg-muted/30 relative group max-w-fit">
					<img
						src={getImageSrc(selectedImage.base64, selectedImage.type)}
						className="h-20 w-32 object-cover rounded border border-border shadow-sm"
						alt="Chart preview"
					/>
					<button
						onClick={removeSelectedImage}
						className="absolute -top-2 -right-2 bg-destructive text-white rounded-full h-5 w-5 flex items-center justify-center shadow-md hover:bg-destructive/90 transition"
						type="button"
					>
						<X className="h-3 w-3" />
					</button>
				</div>
			)}

			{/* Terminal Display */}
			<div className="flex-1 flex flex-col min-h-[200px] bg-black/60 border border-border rounded-xl overflow-hidden font-mono text-xs">
				<div className="bg-background/80 border-b border-slate-950 px-3 py-2 flex items-center justify-between">
					<div className="flex items-center gap-2">
						<TerminalIcon className="w-4 h-4 text-profit shrink-0" />
						<span className="text-muted-foreground/80 font-semibold text-[10px] sm:text-[11px] truncate">AUTOPILOT CONSOLE</span>
					</div>
					{isRunning && (
						<div className="flex items-center gap-1.5 shrink-0 pl-2">
							<span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
							<span className="text-[9px] sm:text-[10px] text-profit font-semibold uppercase truncate">{currentStatus}</span>
						</div>
					)}
				</div>

				<div className="flex-1 p-2 sm:p-3 overflow-y-auto space-y-1.5 scrollbar-thin scrollbar-thumb-slate-800 break-words">
					{logs.length === 0 && (
						<div className="text-slate-600 text-center py-8 sm:py-12 flex flex-col items-center gap-1.5 px-4">
							<TerminalIcon className="w-8 h-8 opacity-40 animate-pulse text-primary mb-2" />
							<span className="text-center">Autopilot terminal ready. Describe your strategy and click Optimize to start.</span>
						</div>
					)}
					{logs.map((log) => (
						<div key={log.id} className="flex items-start gap-2">
							<span className="text-slate-600 shrink-0 select-none">[{log.timestamp}]</span>
							<div className="flex-1 min-w-0 flex items-start">
								<span className={
									log.type === "success" ? "text-profit mr-1.5 shrink-0 select-none" :
									log.type === "warn" ? "text-amber-400 mr-1.5 shrink-0 select-none" :
									log.type === "error" ? "text-rose-500 font-bold mr-1.5 shrink-0 select-none" :
									"text-foreground/80 mr-1.5 shrink-0 select-none"
								}>
									{log.type === "error" ? "✖ " : log.type === "success" ? "✔ " : "> "}
								</span>
								<div className={`flex-1 text-xs whitespace-normal break-words ${
									log.type === "success" ? "text-profit" :
									log.type === "warn" ? "text-amber-400" :
									log.type === "error" ? "text-rose-500" :
									"text-foreground/80"
								}`}>
									<ReactMarkdown
										components={{
											p: ({ node, ...props }) => <span className="block mb-1 last:mb-0 whitespace-pre-wrap" {...props} />,
											ul: ({ node, ...props }) => <ul className="list-disc pl-4 space-y-0.5" {...props} />,
											ol: ({ node, ...props }) => <ol className="list-decimal pl-4 space-y-0.5" {...props} />,
											li: ({ node, ...props }) => <li className="mb-0.5 whitespace-pre-wrap" {...props} />,
											h1: ({ node, ...props }) => <h1 className="block text-sm font-bold text-white mt-1.5 mb-1 whitespace-pre-wrap" {...props} />,
											h2: ({ node, ...props }) => <h2 className="block text-xs font-bold text-white mt-1 mb-1 whitespace-pre-wrap" {...props} />,
											h3: ({ node, ...props }) => <h3 className="block text-xs font-semibold text-white mt-1 mb-0.5 whitespace-pre-wrap" {...props} />,
											strong: ({ node, ...props }) => <strong className="font-bold text-white" {...props} />,
											a: ({ node, ...props }) => <a className="text-primary hover:underline" target="_blank" rel="noopener noreferrer" {...props} />,
										}}
									>
										{log.message}
									</ReactMarkdown>
								</div>
							</div>
						</div>
					))}
					<div ref={terminalEndRef} />
				</div>
			</div>

			{/* Iterations Status Grid */}
			{results.length > 0 && (
				<div className="mt-4 border-t border-border pt-4">
					<h4 className="text-[10px] uppercase font-mono text-muted-foreground mb-2">Candidate Comparison</h4>
					<div className="flex sm:grid sm:grid-cols-5 gap-2.5 overflow-x-auto pb-2 snap-x scrollbar-none">
						{results.map((res) => {
							const isProfitable = res.pnl > 0;
							return (
								<div
									key={res.iteration}
									className={`min-w-[110px] sm:min-w-0 shrink-0 snap-start bg-card border ${
										isProfitable ? "border-profit/20 bg-profit/5" : "border-border bg-card"
									} rounded-lg p-2.5 flex flex-col justify-between`}
								>
									<span className="text-[10px] text-muted-foreground font-mono">Var {chr(64 + res.iteration)}</span>
									<div className={`text-sm font-semibold mt-1 font-mono ${isProfitable ? "text-profit" : "text-loss"}`}>
										{res.pnl > 0 ? "+" : ""}{res.pnl.toFixed(1)}%
									</div>
									<div className="text-[9px] text-muted-foreground/80 mt-0.5">WR: {res.win_rate.toFixed(0)}%</div>
									<div className="text-[9px] text-muted-foreground/80">Tr: {res.trades}</div>
								</div>
							);
						})}
					</div>
				</div>
			)}

			{/* Final Success Card */}
			{finalStrategy && (
				<div className="mt-4 bg-gradient-to-r from-primary/10 via-primary/5 to-transparent border border-primary/30 rounded-xl p-3 sm:p-4 animate-fade-in relative overflow-hidden shadow-primary/5">
					<div className="absolute top-0 right-0 w-24 h-24 bg-primary/10 rounded-full blur-2xl" />
					<div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
						
						<div className="flex items-center gap-3">
							<div className="bg-primary/20 p-2 sm:p-2.5 rounded-lg border border-primary/30 shrink-0">
								<Activity className="w-5 h-5 text-primary/80 animate-pulse" />
							</div>
							<div className="min-w-0">
								<h3 className="font-semibold text-foreground text-sm truncate">
									Best Strategy Configured
								</h3>
								<p className="text-[10px] sm:text-xs text-muted-foreground/80 mt-0.5 truncate">
									{finalStrategy.strategy_name || "VisualBuilderStrategy"} • Standard Engine
								</p>
							</div>
						</div>
						<div className="flex gap-4 sm:gap-6 font-mono w-full lg:w-auto justify-between lg:justify-start">
							<div>
								<div className="text-[9px] text-muted-foreground">PnL</div>
								<div className={`text-sm font-bold ${finalKpis?.pnl > 0 ? "text-profit" : "text-loss"}`}>
									{finalKpis?.pnl > 0 ? "+" : ""}{finalKpis?.pnl?.toFixed(2)}%
								</div>
							</div>
							<div>
								<div className="text-[9px] text-muted-foreground">Win Rate</div>
								<div className="text-sm font-bold text-foreground">
									{finalKpis?.win_rate?.toFixed(1)}%
								</div>
							</div>
							<div>
								<div className="text-[9px] text-muted-foreground">Max DD</div>
								<div className="text-sm font-bold text-foreground">
									-{finalKpis?.max_dd?.toFixed(1)}%
								</div>
							</div>
						</div>
						<button
							onClick={() => onStrategyGenerated(finalStrategy?.config_data || finalStrategy)}
							className="w-full lg:w-auto bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2.5 sm:py-2 text-xs font-semibold flex items-center justify-center gap-1 shadow-lg transition shrink-0"
							type="button"
						>
							HITL Checkpoint: Approve <ArrowRight className="w-4 h-4 ml-1" />
						</button>
					</div>
				</div>
			)}
		</div>
	);
};
