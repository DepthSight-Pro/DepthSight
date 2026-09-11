import type React from "react";
import { useEffect, useRef, useState, useCallback } from "react";
import { Play, Square, Terminal as TerminalIcon, ArrowRight, Activity, Image as ImageIcon, X, Bot, Sparkles, RotateCcw } from "lucide-react";
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
	onStrategyGenerated: (strategyJson: Record<string, any>) => void;
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
	const [finalStrategy, setFinalStrategy] = useState<Record<string, any> | null>(() => {
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
	const terminalContainerRef = useRef<HTMLDivElement>(null);
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

	// Auto-scroll ONLY terminal container
	useEffect(() => {
		if (terminalContainerRef.current) {
			terminalContainerRef.current.scrollTop = terminalContainerRef.current.scrollHeight;
		}
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

		let WS_URL = "";
		if (import.meta.env.DEV) {
			const wsDev = import.meta.env.VITE_WS_URL;
			const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
			WS_URL = wsDev || `${wsProtocol}//${window.location.hostname}:8765/ws`;
		} else {
			const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
			const host = window.location.host;
			WS_URL = `${protocol}//${host}/ws`;
		}

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
		<div className="flex flex-col h-full bg-card border border-border rounded-2xl overflow-hidden shadow-2xl p-4">
			{/* Top Control Bar */}
			<div className="flex items-center justify-between border-b border-border pb-3 mb-3 shrink-0">
				<div className="flex items-center gap-2">
					<div className="p-1.5 rounded-lg bg-primary/10 text-primary border border-primary/20">
						<Bot className="w-4 h-4" />
					</div>
					<div>
						<div className="flex items-center gap-2">
							<h3 className="font-semibold text-foreground text-sm">Autopilot Agent</h3>
							{isRunning ? (
								<span className="inline-flex items-center gap-1.5 text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
									<span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
									<span className="uppercase font-semibold">{currentStatus}</span>
									<span>(Iter {currentIteration})</span>
								</span>
							) : (
								<span className="inline-flex items-center gap-1.5 text-[10px] font-mono px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground border border-border">
									<span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
									idle
								</span>
							)}
						</div>
					</div>
				</div>

				<div className="flex items-center gap-2">
					<div className="flex items-center gap-1.5">
						<span className="text-[10px] uppercase font-mono text-muted-foreground hidden sm:inline">Budget:</span>
						<select
							value={maxIterations}
							onChange={(e) => {
								const val = e.target.value;
								setMaxIterations(isNaN(Number(val)) ? val : Number(val));
							}}
							disabled={isRunning}
							className="bg-background border border-border rounded-lg px-2.5 py-1 text-xs text-foreground focus:outline-none focus:border-primary disabled:opacity-50 transition cursor-pointer font-sans"
							title="Maximum backtest optimization runs"
						>
							<option value={5}>5 runs</option>
							<option value={10}>10 runs</option>
							<option value={20}>20 runs</option>
							<option value="until_profitable">Until Profit</option>
						</select>
					</div>

					<button
						onClick={() => {
							if (logs.length > 0 && confirm("Clear conversation and log history?")) {
								setLogs([]);
								setResults([]);
								setFinalStrategy(null);
								setFinalKpis(null);
								localStorage.removeItem("autopilot_logs");
								localStorage.removeItem("autopilot_results");
								localStorage.removeItem("autopilot_final_strategy");
								localStorage.removeItem("autopilot_final_kpis");
							}
						}}
						disabled={isRunning || logs.length === 0}
						className="p-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-muted/50 transition disabled:opacity-40"
						title="Clear logs"
						type="button"
					>
						<RotateCcw className="w-3.5 h-3.5" />
					</button>
				</div>
			</div>

			{/* Main Scrollable Chat & Console Area */}
			<div ref={terminalContainerRef} className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-3 scrollbar-thin scrollbar-thumb-slate-800">
				{logs.length === 0 && (
					<div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-4 my-auto">
						<div className="p-4 rounded-2xl bg-gradient-to-b from-primary/20 to-primary/5 border border-primary/20 shadow-inner">
							<Sparkles className="w-8 h-8 text-primary animate-pulse" />
						</div>
						<div className="max-w-md space-y-1.5">
							<h4 className="text-base font-semibold text-foreground">
								Autonomous Strategy Autopilot
							</h4>
							<p className="text-xs text-muted-foreground leading-relaxed">
								Describe your trading hypothesis, indicators, or target market. 
								The agent will autonomously synthesize rules, execute vector backtests, and mutate parameters to find optimal alpha.
							</p>
						</div>

						{/* Quick Prompt Suggestions */}
						<div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg w-full pt-2">
							{[
								"Mean-reversion strategy on ETHUSDT using RSI & Bollinger Bands",
								"Breakout strategy on BTCUSDT 15m with ADX trend filter and volume confirmation",
								"High-frequency momentum scalping on SOLUSDT with ATR trailing stop",
								"Volatility squeeze breakout with pre-breakout consolidation filter"
							].map((suggestion) => (
								<button
									key={suggestion}
									type="button"
									onClick={() => setPrompt(suggestion)}
									className="text-left text-[11px] p-2.5 rounded-xl border border-border bg-card/60 hover:bg-muted/60 hover:border-primary/40 text-muted-foreground hover:text-foreground transition leading-snug"
								>
									💡 {suggestion}
								</button>
							))}
						</div>
					</div>
				)}

				{/* Terminal Logs (Console Stream) */}
				{logs.length > 0 && (
					<div className="flex flex-col bg-black/60 border border-border rounded-xl p-3 font-mono text-xs space-y-1.5">
						<div className="flex items-center justify-between border-b border-slate-900 pb-2 mb-1 text-[11px] text-muted-foreground">
							<div className="flex items-center gap-1.5">
								<TerminalIcon className="w-3.5 h-3.5 text-profit" />
								<span>Agent Execution Stream</span>
							</div>
							<span className="text-[10px]">{logs.length} events logged</span>
						</div>
						{logs.map((log) => (
							<div key={log.id} className="flex items-start gap-2">
								<span className="text-slate-600 shrink-0 select-none text-[11px]">[{log.timestamp}]</span>
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
					</div>
				)}

				{/* Iterations Status Grid */}
				{results.length > 0 && (
					<div className="border border-border rounded-xl p-3 bg-card/50">
						<h4 className="text-[10px] uppercase font-mono text-muted-foreground mb-2">Backtest Candidate Comparison</h4>
						<div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
							{results.map((res) => {
								const isProfitable = res.pnl > 0;
								return (
									<div
										key={res.iteration}
										className={`bg-card border ${
											isProfitable ? "border-profit/25 bg-profit/5" : "border-border bg-card"
										} rounded-lg p-2 flex flex-col justify-between`}
									>
										<span className="text-[10px] text-muted-foreground font-mono">Var {chr(64 + res.iteration)}</span>
										<div className={`text-sm font-semibold mt-0.5 font-mono ${isProfitable ? "text-profit" : "text-loss"}`}>
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

				{/* Final Strategy Card */}
				{finalStrategy && (
					<div className="bg-gradient-to-r from-primary/15 via-primary/5 to-transparent border border-primary/30 rounded-xl p-3.5 relative overflow-hidden shadow-primary/5">
						<div className="absolute top-0 right-0 w-24 h-24 bg-primary/10 rounded-full blur-2xl pointer-events-none" />
						<div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 relative z-10">
							<div className="flex items-center gap-2.5">
								<div className="bg-primary/20 p-2 rounded-lg border border-primary/30 shrink-0">
									<Activity className="w-5 h-5 text-primary/80 animate-pulse" />
								</div>
								<div>
									<h3 className="font-semibold text-foreground text-sm">
										Best Strategy Configured
									</h3>
									<p className="text-xs text-muted-foreground/80">
										{finalStrategy.strategy_name || "VisualBuilderStrategy"} • Standard Engine
									</p>
								</div>
							</div>

							<div className="flex gap-4 font-mono text-center">
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
								className="w-full sm:w-auto bg-primary hover:bg-primary/90 text-white rounded-lg px-3.5 py-2 text-xs font-semibold flex items-center justify-center gap-1.5 shadow-lg shadow-primary/25 transition cursor-pointer active:scale-[0.98]"
								type="button"
							>
								Approve & Load to Editor <ArrowRight className="w-4 h-4 ml-1" />
							</button>
						</div>
					</div>
				)}
			</div>

			{/* Bottom Chat Input Form */}
			<div className="pt-3 border-t border-border mt-auto shrink-0 space-y-2">
				{/* Image Preview (attached above textarea) */}
				{selectedImage && (
					<div className="flex items-center gap-2 border border-border rounded-xl p-2 bg-muted/40 max-w-fit animate-in fade-in">
						<div className="relative group">
							<img
								src={getImageSrc(selectedImage.base64, selectedImage.type)}
								className="h-16 w-24 object-cover rounded-lg border border-border shadow-sm"
								alt="Chart preview"
							/>
							<button
								onClick={removeSelectedImage}
								className="absolute -top-1.5 -right-1.5 bg-destructive text-white rounded-full h-5 w-5 flex items-center justify-center shadow-md hover:bg-destructive/90 transition"
								type="button"
								title="Remove image"
							>
								<X className="h-3 w-3" />
							</button>
						</div>
						<div className="text-xs text-muted-foreground pr-2">
							<p className="font-medium text-foreground">Chart screenshot attached</p>
							<p className="text-[10px]">Will be analyzed during strategy generation</p>
						</div>
					</div>
				)}

				{/* Classic Multi-line Chat Textarea */}
				<div className="relative rounded-2xl border border-border bg-background/90 focus-within:border-primary focus-within:ring-1 focus-within:ring-primary/20 shadow-lg transition-all">
					<textarea
						id="agent-prompt"
						value={prompt}
						onChange={(e) => setPrompt(e.target.value)}
						onKeyDown={(e) => {
							if (e.key === "Enter" && !e.shiftKey) {
								e.preventDefault();
								if (!isRunning && prompt.trim()) {
									startAutopilot();
								}
							}
						}}
						disabled={isRunning}
						rows={2}
						placeholder="Message Autopilot Agent (Enter to optimize, Shift+Enter for new line)..."
						className="w-full bg-transparent px-3.5 pt-3 pb-11 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none resize-none disabled:opacity-50 scrollbar-thin"
					/>

					<div className="absolute bottom-2 left-3 right-3 flex items-center justify-between pointer-events-none">
						<div className="flex items-center gap-1.5 pointer-events-auto">
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
								className="p-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:border-primary transition disabled:opacity-50 flex items-center gap-1 text-xs"
								type="button"
								title="Attach chart screenshot"
							>
								<ImageIcon className="w-3.5 h-3.5" />
								<span className="text-[10px] hidden sm:inline">Attach Chart</span>
							</button>
						</div>

						<div className="flex items-center gap-2 pointer-events-auto">
							{isRunning ? (
								<button
									onClick={() => stopAutopilot(false)}
									className="bg-destructive hover:bg-destructive/90 text-white rounded-xl px-4 py-1.5 flex items-center gap-1.5 text-xs font-semibold shadow-md transition"
									type="button"
								>
									<Square className="w-3.5 h-3.5 fill-white" /> Stop
								</button>
							) : (
								<button
									onClick={startAutopilot}
									disabled={!prompt.trim()}
									className="bg-primary hover:bg-primary/90 text-white rounded-xl px-4 py-1.5 flex items-center gap-1.5 text-xs font-semibold shadow-md shadow-primary/20 transition disabled:opacity-40 cursor-pointer"
									type="button"
								>
									<Play className="w-3.5 h-3.5 fill-white" /> Optimize
								</button>
							)}
						</div>
					</div>
				</div>
			</div>
		</div>
	);
};
