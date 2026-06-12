import { motion } from "framer-motion";
import {
	Activity,
	ArrowRight,
	BookOpen,
	Calendar,
	ChevronLeft,
	ChevronRight,
	Clock,
	Cpu,
	Download,
	Globe,
	MessageSquare,
	Network,
	Newspaper,
	Paperclip,
	Pin,
	Plus,
	Send,
	Settings,
	Sparkles,
	ThumbsUp,
	Trash2,
	TrendingUp,
	User as UserIcon,
	X,
} from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
	Area as MiniArea,
	AreaChart as MiniAreaChart,
	ResponsiveContainer as MiniResponsiveContainer,
} from "recharts";
import { toast } from "sonner";
import { EquityCurveChart } from "@/components/research/EquityCurveChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import { useSaveStrategyConfig } from "@/lib/api";
import { cn } from "@/lib/utils";

interface NewsItem {
	id?: number;
	title: string;
	date: string;
	text: string;
	likes_count?: number;
	comments_count?: number;
	is_pinned?: boolean;
}

interface HubTopicResponse {
	id: string;
	topic_type: string;
	title: string;
	description: string;
	author_name: string;
	symbol?: string;
	period_start?: string;
	period_end?: string;
	kpis?: {
		total_pnl: number;
		sharpe_ratio: number;
		win_rate: number;
		max_drawdown: number;
		trades: number;
	};
	equity_curve?: [number, number][];
	strategy_json?: Record<string, unknown>;
	likes_count: number;
	comments_count: number;
	is_verified?: boolean;
	tags?: string[];
	name?: string;
	author?: string;
	created_at: string;
	is_admin?: boolean;
}

interface HubCommentResponse {
	id: number;
	topic_id: string;
	author_name: string;
	text: string;
	created_at: string;
	is_admin?: boolean;
}

interface HubNodeResponse {
	name: string;
	latitude?: number;
	longitude?: number;
	city?: string;
	country?: string;
	latency_ms?: number;
	version?: string;
	is_master: boolean;
}

// Sparkline area chart for card preview
const MiniEquityChart: React.FC<{ data: [number, number][] }> = ({ data }) => {
	const chartData = React.useMemo(() => {
		if (!data || data.length === 0) return [];
		return data.map(([, value]) => ({
			value: Number(value),
		}));
	}, [data]);

	if (chartData.length === 0) return null;

	return (
		<div className="h-12 w-full opacity-60">
			<MiniResponsiveContainer width="100%" height="100%">
				<MiniAreaChart data={chartData}>
					<MiniArea
						type="monotone"
						dataKey="value"
						stroke="hsl(var(--primary))"
						strokeWidth={1.5}
						fill="hsl(var(--primary) / 0.05)"
						dot={false}
					/>
				</MiniAreaChart>
			</MiniResponsiveContainer>
		</div>
	);
};

const getTopicTitle = (
	topic: HubTopicResponse,
	t: (key: string, options?: unknown) => string,
): string => {
	if (topic.topic_type !== "strategy") return topic.title;
	if (topic.title && topic.title !== "VisualBuilderStrategy")
		return topic.title;

	const strategy = topic.strategy_json as Record<string, unknown>;
	if (!strategy)
		return (
			topic.title || t("community:verified.sharedStrategy", "Shared Strategy")
		);

	const params = (strategy.parameters || strategy) as Record<string, unknown>;
	const config = (strategy.config || strategy) as Record<string, unknown>;
	return (
		(params.name as string) ||
		(params.strategy_display_name as string) ||
		(config.name as string) ||
		topic.title ||
		t("community:verified.sharedStrategy", "Shared Strategy")
	);
};

const NetworkMap: React.FC<{
	activeNodes: HubNodeResponse[];
	isRu: boolean;
	t: (key: string, options?: unknown) => string;
}> = ({ activeNodes, isRu, t }) => {
	const canvasRef = useRef<HTMLCanvasElement | null>(null);
	const [geoData, setGeoData] = useState<any>(null);

	// Zoom and Pan states using refs to prevent React re-renders during high-frequency mouse dragging
	const zoomRef = useRef(1.4);
	const offsetXRef = useRef(0.0);
	const offsetYRef = useRef(0.0);
	const isDraggingRef = useRef(false);
	const dragStartRef = useRef({ x: 0, y: 0 });

	useEffect(() => {
		fetch("/geo.json")
			.then((res) => {
				if (!res.ok) throw new Error("Failed to load map data");
				return res.json();
			})
			.then((data) => {
				setGeoData(data);
			})
			.catch((err) => {
				console.error("Error loading geo.json:", err);
			});
	}, []);

	useEffect(() => {
		const canvas = canvasRef.current;
		if (!canvas) return;

		const ctx = canvas.getContext("2d");
		if (!ctx) return;
		let animationFrameId: number;

		// Create offscreen canvas for static background caching (grid & map)
		const offscreenCanvas = document.createElement("canvas");
		const offscreenCtx = offscreenCanvas.getContext("2d");

		// Projection formula mapping lon/lat to canvas coordinates
		const project = (lon: number, lat: number, w: number, h: number, z: number, ox: number, oy: number) => {
			const scaleX = 1.05; // Zoomed in horizontally
			const scaleY = 0.95; // Zoomed in vertically
			const baseX = ( (1 - scaleX) / 2 + ((lon + 180) / 360) * scaleX ) * w;
			// Shift the map up/down slightly (h * 0.05) to focus on the northern hemisphere where 99% of nodes are
			const baseY = ( (1 - scaleY) / 2 + ((90 - lat) / 180) * scaleY ) * h + (h * 0.05);

			// Zoom and Pan relative to the center of the canvas
			const centerX = w / 2;
			const centerY = h / 2;
			const x = (baseX - centerX) * z + centerX + ox;
			const y = (baseY - centerY) * z + centerY + oy;

			return [x, y];
		};

		const drawGrid = (c: CanvasRenderingContext2D) => {
			c.strokeStyle = "rgba(30, 41, 59, 0.25)";
			c.lineWidth = 1;
			const step = 25;
			for (let x = 0; x < canvas.width; x += step) {
				c.beginPath();
				c.moveTo(x, 0);
				c.lineTo(x, canvas.height);
				c.stroke();
			}
			for (let y = 0; y < canvas.height; y += step) {
				c.beginPath();
				c.moveTo(0, y);
				c.lineTo(canvas.width, y);
				c.stroke();
			}
		};

		const preRenderBackground = () => {
			if (!offscreenCtx) return;
			offscreenCtx.clearRect(0, 0, offscreenCanvas.width, offscreenCanvas.height);

			// Draw Grid
			drawGrid(offscreenCtx);

			// Draw World Map Contours from geo.json at base scale (zoom = 1, offsets = 0)
			if (geoData) {
				offscreenCtx.save();
				offscreenCtx.strokeStyle = "rgba(6, 182, 212, 0.25)"; // neon cyan outline
				offscreenCtx.fillStyle = "rgba(15, 23, 42, 0.45)";     // dark slate background
				offscreenCtx.lineWidth = 0.8;

				geoData.features?.forEach((feature: any) => {
					const geom = feature.geometry;
					if (!geom) return;

					const drawPolygon = (coordinates: number[][][]) => {
						coordinates.forEach((ring) => {
							if (ring.length < 2) return;
							offscreenCtx.beginPath();
							const [startX, startY] = project(ring[0][0], ring[0][1], offscreenCanvas.width, offscreenCanvas.height, 1.0, 0, 0);
							offscreenCtx.moveTo(startX, startY);
							for (let i = 1; i < ring.length; i++) {
								const [px, py] = project(ring[i][0], ring[i][1], offscreenCanvas.width, offscreenCanvas.height, 1.0, 0, 0);
								offscreenCtx.lineTo(px, py);
							}
							offscreenCtx.closePath();
							offscreenCtx.stroke();
							offscreenCtx.fill();
						});
					};

					if (geom.type === "Polygon") {
						drawPolygon(geom.coordinates);
					} else if (geom.type === "MultiPolygon") {
						geom.coordinates.forEach((poly: any) => drawPolygon(poly));
					}
				});
				offscreenCtx.restore();
			}
		};

		// Resizing
		const resizeCanvas = () => {
			if (canvas?.parentElement) {
				canvas.width = canvas.parentElement.clientWidth;
				canvas.height = canvas.parentElement.clientHeight || Math.max(650, Math.round(canvas.width * 0.5));
			} else {
				canvas.width = 800;
				canvas.height = 650;
			}

			offscreenCanvas.width = canvas.width;
			offscreenCanvas.height = canvas.height;

			preRenderBackground();
		};

		resizeCanvas();
		window.addEventListener("resize", resizeCanvas);

		// Interactive Zoom and Drag Handlers
		const handleWheel = (e: WheelEvent) => {
			e.preventDefault();
			const zoomSpeed = 0.08;
			const prevZoom = zoomRef.current;
			
			// Calculate new zoom factor
			if (e.deltaY < 0) {
				zoomRef.current = Math.min(6.0, zoomRef.current + zoomSpeed * zoomRef.current);
			} else {
				zoomRef.current = Math.max(0.7, zoomRef.current - zoomSpeed * zoomRef.current);
			}

			// Zoom centering math (zooms into the mouse pointer location)
			const rect = canvas.getBoundingClientRect();
			const mouseX = e.clientX - rect.left;
			const mouseY = e.clientY - rect.top;

			const zoomRatio = zoomRef.current / prevZoom;
			offsetXRef.current = mouseX - (mouseX - offsetXRef.current) * zoomRatio;
			offsetYRef.current = mouseY - (mouseY - offsetYRef.current) * zoomRatio;
		};

		const handleMouseDown = (e: MouseEvent) => {
			isDraggingRef.current = true;
			dragStartRef.current = { x: e.clientX - offsetXRef.current, y: e.clientY - offsetYRef.current };
			canvas.style.cursor = "grabbing";
		};

		const handleMouseMove = (e: MouseEvent) => {
			if (!isDraggingRef.current) return;
			offsetXRef.current = e.clientX - dragStartRef.current.x;
			offsetYRef.current = e.clientY - dragStartRef.current.y;
		};

		const handleMouseUp = () => {
			isDraggingRef.current = false;
			canvas.style.cursor = "grab";
		};

		canvas.addEventListener("wheel", handleWheel, { passive: false });
		canvas.addEventListener("mousedown", handleMouseDown);
		canvas.addEventListener("mousemove", handleMouseMove);
		canvas.addEventListener("mouseup", handleMouseUp);
		canvas.addEventListener("mouseleave", handleMouseUp);
		canvas.style.cursor = "grab";

		const safeT = typeof t === "function" ? t : (key: string) => key;
		const isNodesArray = Array.isArray(activeNodes);
		const masterNode = isNodesArray
			? activeNodes.find((n) => n.is_master)
			: null;
		const masterVersion = masterNode?.version || "1.0.0";

		const nodes =
			isNodesArray && activeNodes.length > 0
				? activeNodes.map((node, index) => {
						const lat = node.latitude ?? 50.1109;
						const lon = node.longitude ?? 8.6821;
						const nodeName = node.is_master
							? safeT("community:network.nodes.frankfurt") || node.name
							: node.city
								? `${node.name} (${node.city}, ${node.country || ""})`
								: node.name;
						const isOutdated =
							!node.is_master && node.version && node.version !== masterVersion;
						const displayName = `${nodeName} [v${node.version || "1.0.0"}]${isOutdated ? " (Outdated)" : ""}`;
						return {
							name: displayName,
							lat,
							lon,
							size: node.is_master ? 6 : 4,
							pulse: index,
							speed: node.is_master ? 0.05 : 0.03,
							master: node.is_master,
							color: node.is_master
								? "#3b82f6"
								: isOutdated
									? "#eab308"
									: "#10b981",
						};
					})
				: [
						{
							name: safeT("community:network.nodes.frankfurt"),
							lat: 50.1109,
							lon: 8.6821,
							size: 6,
							pulse: 0,
							speed: 0.05,
							master: true,
							color: "#3b82f6",
						},
						{
							name: safeT("community:network.nodes.newYork"),
							lat: 40.7128,
							lon: -74.006,
							size: 4,
							pulse: 1,
							speed: 0.03,
							master: false,
							color: "#10b981",
						},
						{
							name: safeT("community:network.nodes.singapore"),
							lat: 1.3521,
							lon: 103.8198,
							size: 4,
							pulse: 2,
							speed: 0.04,
							master: false,
							color: "#10b981",
						},
						{
							name: safeT("community:network.nodes.tokyo"),
							lat: 35.6762,
							lon: 139.6503,
							size: 4,
							pulse: 0.5,
							speed: 0.02,
							master: false,
							color: "#10b981",
						},
						{
							name: safeT("community:network.nodes.siliconValley"),
							lat: 37.7749,
							lon: -122.4194,
							size: 4,
							pulse: 2.5,
							speed: 0.025,
							master: false,
							color: "#10b981",
						},
						{
							name: safeT("community:network.nodes.sydney"),
							lat: -33.8688,
							lon: 151.2093,
							size: 4,
							pulse: 3,
							speed: 0.015,
							master: false,
							color: "#10b981",
						},
					];

		const drawNodesAndConnections = (time: number) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);

			// Draw pre-rendered background grid and world map (scaled/translated dynamically on main context)
			ctx.save();
			ctx.translate(canvas.width / 2 + offsetXRef.current, canvas.height / 2 + offsetYRef.current);
			ctx.scale(zoomRef.current, zoomRef.current);
			ctx.drawImage(offscreenCanvas, -canvas.width / 2, -canvas.height / 2);
			ctx.restore();

			// Project nodes in real-time to match the zoom and pan settings
			const calculatedNodes = nodes.map((node) => {
				const [realX, realY] = project(node.lon, node.lat, canvas.width, canvas.height, zoomRef.current, offsetXRef.current, offsetYRef.current);
				return {
					...node,
					realX,
					realY,
				};
			});

			// Draw Connections
			calculatedNodes.forEach((nodeA) => {
				calculatedNodes.forEach((nodeB) => {
					if (nodeA !== nodeB) {
						const distance = Math.hypot(
							nodeA.realX - nodeB.realX,
							nodeA.realY - nodeB.realY,
						);
						// Connections scale dynamically with zoom to preserve topology logic
						if (nodeA.master || distance < canvas.width * 0.35 * zoomRef.current) {
							ctx.beginPath();
							ctx.moveTo(nodeA.realX, nodeA.realY);
							ctx.lineTo(nodeB.realX, nodeB.realY);
							const grad = ctx.createLinearGradient(
								nodeA.realX,
								nodeA.realY,
								nodeB.realX,
								nodeB.realY,
							);
							const pulsePos = (time * 0.05 + distance * 0.01) % 1;
							grad.addColorStop(0, "rgba(59, 130, 246, 0.05)");
							grad.addColorStop(pulsePos, "rgba(96, 165, 250, 0.4)");
							grad.addColorStop(1, "rgba(16, 185, 129, 0.05)");
							ctx.strokeStyle = grad;
							ctx.lineWidth = 1;
							ctx.stroke();
						}
					}
				});
			});

			// Draw Nodes
			calculatedNodes.forEach((node) => {
				const pulseRadius =
					node.size * (1 + Math.sin(time * 0.05 + node.pulse) * 0.4);

				// Glow
				ctx.beginPath();
				ctx.arc(node.realX, node.realY, pulseRadius * 2.2, 0, Math.PI * 2);
				ctx.fillStyle = node.master
					? "rgba(59, 130, 246, 0.15)"
					: "rgba(16, 185, 129, 0.12)";
				ctx.fill();

				// Core
				ctx.beginPath();
				ctx.arc(node.realX, node.realY, node.size, 0, Math.PI * 2);
				ctx.fillStyle = node.color;
				ctx.fill();

				// Label
				ctx.font = "9px monospace";
				ctx.fillStyle = "#94a3b8";
				ctx.fillText(node.name, node.realX + 10, node.realY + 3);
			});
		};

		let time = 0;
		const render = () => {
			time++;
			drawNodesAndConnections(time);
			animationFrameId = requestAnimationFrame(render);
		};
		render();

		return () => {
			cancelAnimationFrame(animationFrameId);
			window.removeEventListener("resize", resizeCanvas);
			canvas.removeEventListener("wheel", handleWheel);
			canvas.removeEventListener("mousedown", handleMouseDown);
			canvas.removeEventListener("mousemove", handleMouseMove);
			canvas.removeEventListener("mouseup", handleMouseUp);
			canvas.removeEventListener("mouseleave", handleMouseUp);
		};
	}, [activeNodes, isRu, t, geoData]);

	return <canvas ref={canvasRef} className="block w-full" />;
};

const CommunityHub = () => {
	const { t, i18n } = useTranslation(["navigation", "common", "community"]);
	const isRu = i18n.language.startsWith("ru");
	const navigate = useNavigate();
	const saveConfig = useSaveStrategyConfig();
	const { user } = useAuth();
	const hubApiUrl =
		import.meta.env.VITE_HUB_API_URL || "https://app.depthsight.pro/api/v1/hub";

	// State
	const [activeTab, setActiveTab] = useState("verified");
	const [verifiedStrategies, setVerifiedStrategies] = useState<
		HubTopicResponse[]
	>([]);
	const [news, setNews] = useState<NewsItem[]>([]);
	const [sharedStrategies, setSharedStrategies] = useState<HubTopicResponse[]>(
		[],
	);
	const [discussions, setDiscussions] = useState<HubTopicResponse[]>([]);

	const [loadingVerified, setLoadingVerified] = useState(true);
	const [loadingNews, setLoadingNews] = useState(true);
	const [loadingShared, setLoadingShared] = useState(true);
	const [loadingDiscussions, setLoadingDiscussions] = useState(true);
	const [verifiedPage, setVerifiedPage] = useState(1);
	const [communityPage, setCommunityPage] = useState(1);
	const [newsPage, setNewsPage] = useState(1);

	// Like tracking scoped to account
	const username = user?.username || "anonymous";
	const [likedTopics, setLikedTopics] = useState<string[]>([]);
	const [likedNews, setLikedNews] = useState<number[]>([]);

	const PRESETS_PER_PAGE = 9;
	const COMMUNITY_PER_PAGE = 9;
	const NEWS_PER_PAGE = 3;

	useEffect(() => {
		const storedTopics = localStorage.getItem(
			`depthsight_liked_topics_${username}`,
		);
		if (storedTopics) {
			try {
				setLikedTopics(JSON.parse(storedTopics));
			} catch {
				void 0;
			}
		} else {
			setLikedTopics([]);
		}

		const storedNews = localStorage.getItem(
			`depthsight_liked_news_${username}`,
		);
		if (storedNews) {
			try {
				setLikedNews(JSON.parse(storedNews));
			} catch {
				void 0;
			}
		} else {
			setLikedNews([]);
		}
	}, [username]);

	useEffect(() => {
		setVerifiedPage(1);
	}, []);

	useEffect(() => {
		setCommunityPage(1);
	}, []);

	useEffect(() => {
		setNewsPage(1);
	}, []);

	// Feedback Form State
	const [category, setCategory] = useState("bug");
	const [feedbackText, setFeedbackText] = useState("");
	const [contactEmail, setContactEmail] = useState("");
	const [submittingFeedback, setSubmittingFeedback] = useState(false);
	const [localFeedbackTickets, setLocalFeedbackTickets] = useState<
		Record<string, unknown>[]
	>([]);

	useEffect(() => {
		const stored = localStorage.getItem("depthsight_hub_feedback_tickets");
		if (stored) {
			try {
				setLocalFeedbackTickets(JSON.parse(stored));
			} catch {
				void 0;
			}
		}
	}, []);

	// Selected Hub Ticket (for chat dialogue modal)
	const [selectedHubTicket, setSelectedHubTicket] = useState<Record<
		string,
		unknown
	> | null>(null);
	const [hubTicketStatus, setHubTicketStatus] = useState<string>("OPEN");
	const [hubTicketMessages, setHubTicketMessages] = useState<
		Record<string, unknown>[]
	>([]);
	const [loadingHubMessages, setLoadingHubMessages] = useState(false);
	const [newHubReply, setNewHubReply] = useState("");
	const [submittingHubReply, setSubmittingHubReply] = useState(false);
	const [updatingHubStatus, setUpdatingHubStatus] = useState(false);
	const [newHubImage, setNewHubImage] = useState<string | null>(null);
	const hubReplyFileRef = React.useRef<HTMLInputElement>(null);

	const [lastReadHubMap, setLastReadHubMap] = useState<Record<string, string>>(
		{},
	);
	const [hubTicketsMessages, setHubTicketsMessages] = useState<
		Record<string, Record<string, unknown>[]>
	>({});

	useEffect(() => {
		const stored = localStorage.getItem("depthsight_hub_last_read");
		if (stored) {
			try {
				setLastReadHubMap(JSON.parse(stored));
			} catch {
				void 0;
			}
		}
	}, []);

	const fetchAllHubMessages = React.useCallback(async () => {
		if (localFeedbackTickets.length === 0) return;
		const newMessagesMap: Record<string, Record<string, unknown>[]> = {};
		await Promise.all(
			localFeedbackTickets.map(async (ticket) => {
				const ticketId = ticket.id as string;
				try {
					const res = await fetch(`${hubApiUrl}/tickets/${ticketId}/messages`);
					if (res.ok) {
						const data = await res.json();
						newMessagesMap[ticketId] = data;
					}
				} catch (err) {
					console.error(
						"Failed to fetch messages for hub ticket",
						ticketId,
						err,
					);
				}
			}),
		);
		setHubTicketsMessages((prev) => ({ ...prev, ...newMessagesMap }));
	}, [localFeedbackTickets, hubApiUrl]);

	useEffect(() => {
		fetchAllHubMessages();
		const interval = setInterval(fetchAllHubMessages, 30000); // poll every 30 seconds
		return () => clearInterval(interval);
	}, [fetchAllHubMessages]);

	useEffect(() => {
		if (selectedHubTicket) {
			const ticketId = selectedHubTicket.id as string;
			setLastReadHubMap((prev) => {
				const updated = {
					...prev,
					[ticketId]: new Date().toISOString(),
				};
				localStorage.setItem(
					"depthsight_hub_last_read",
					JSON.stringify(updated),
				);
				return updated;
			});
		}
	}, [selectedHubTicket]);

	const getHubTicketUnreadCount = (ticketId: string) => {
		const ticketMessages = hubTicketsMessages[ticketId];
		if (!ticketMessages) return 0;
		const lastReadStr = lastReadHubMap[ticketId];
		if (!lastReadStr) {
			return ticketMessages.filter((msg) => msg.isAdmin).length;
		}
		const lastReadTime = new Date(lastReadStr).getTime();
		return ticketMessages.filter((msg) => {
			if (!msg.isAdmin) return false;
			return new Date(msg.createdAt as string).getTime() > lastReadTime;
		}).length;
	};

	useEffect(() => {
		if (selectedHubTicket) {
			const ticketId = selectedHubTicket.id as string;
			fetch(`${hubApiUrl}/tickets/${ticketId}/status`)
				.then((res) => {
					if (!res.ok) throw new Error();
					return res.json();
				})
				.then((data) => {
					setHubTicketStatus(data.status);
				})
				.catch(() => {
					void 0;
				});

			setLoadingHubMessages(true);
			fetch(`${hubApiUrl}/tickets/${ticketId}/messages`)
				.then((res) => {
					if (!res.ok) throw new Error();
					return res.json();
				})
				.then((data) => {
					setHubTicketMessages(data);
					setLoadingHubMessages(false);
				})
				.catch(() => {
					setLoadingHubMessages(false);
				});
		}
	}, [selectedHubTicket, hubApiUrl]);

	// Detailed View Dialog State
	const [selectedTopic, setSelectedTopic] = useState<HubTopicResponse | null>(
		null,
	);
	const [comments, setComments] = useState<HubCommentResponse[]>([]);
	const [loadingComments, setLoadingComments] = useState(false);
	const [newCommentText, setNewCommentText] = useState("");
	const [submittingComment, setSubmittingComment] = useState(false);

	// News detailed view and comments state
	const [selectedNews, setSelectedNews] = useState<NewsItem | null>(null);
	const [newsComments, setNewsComments] = useState<Record<string, unknown>[]>(
		[],
	);
	const [loadingNewsComments, setLoadingNewsComments] = useState(false);
	const [newNewsCommentText, setNewNewsCommentText] = useState("");
	const [submittingNewsComment, setSubmittingNewsComment] = useState(false);

	// Create Discussion Dialog State
	const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
	const [newTopicTitle, setNewTopicTitle] = useState("");
	const [newTopicDesc, setNewTopicDesc] = useState("");
	const [publishingTopic, setPublishingTopic] = useState(false);

	// Admin / Moderator State
	const [adminKey, setAdminKey] = useState<string | null>(
		localStorage.getItem("depthsight_hub_admin_key"),
	);

	// Add News Form State
	const [isAddNewsOpen, setIsAddNewsOpen] = useState(false);
	const [newsTitle, setNewsTitle] = useState("");
	const [newsText, setNewsText] = useState("");
	const [publishingNews, setPublishingNews] = useState(false);

	const [activeNodes, setActiveNodes] = useState<HubNodeResponse[]>([]);

	const fetchActiveNodes = React.useCallback(() => {
		fetch(`${hubApiUrl}/nodes`)
			.then((res) => {
				if (!res.ok) throw new Error();
				return res.json();
			})
			.then((data) => {
				if (Array.isArray(data)) {
					setActiveNodes(data);
				} else {
					console.error("Fetched active nodes data is not an array:", data);
					setActiveNodes([]);
				}
			})
			.catch((e) => {
				console.error("Failed to fetch active nodes", e);
				setActiveNodes([]);
			});
	}, [hubApiUrl]);

	useEffect(() => {
		fetchActiveNodes();
		const interval = setInterval(fetchActiveNodes, 30000);
		return () => clearInterval(interval);
	}, [fetchActiveNodes]);

	const avgLatency = React.useMemo(() => {
		const nonMaster = activeNodes.filter((n) => !n.is_master);
		if (nonMaster.length === 0) return 42;
		const sum = nonMaster.reduce((acc, n) => acc + (n.latency_ms ?? 0), 0);
		return Math.round(sum / nonMaster.length);
	}, [activeNodes]);



	// Initial fetch functions
	const fetchVerified = React.useCallback(() => {
		setLoadingVerified(true);
		fetch(`${hubApiUrl}/strategies`)
			.then((res) => {
				if (!res.ok) throw new Error();
				return res.json();
			})
			.then((data) => {
				setVerifiedStrategies(data);
				setLoadingVerified(false);
			})
			.catch(() => {
				toast.error(
					t(
						"community:verified.loadFailed",
						"Failed to load verified templates",
					),
				);
				setLoadingVerified(false);
			});
	}, [t, hubApiUrl]);

	const fetchNews = React.useCallback(() => {
		setLoadingNews(true);
		fetch(`${hubApiUrl}/news`)
			.then((res) => {
				if (!res.ok) throw new Error();
				return res.json();
			})
			.then((data) => {
				setNews(data);
				setLoadingNews(false);
			})
			.catch(() => {
				toast.error(t("community:news.loadFailed", "Failed to load hub news"));
				setLoadingNews(false);
			});
	}, [t, hubApiUrl]);

	const fetchSharedStrategies = React.useCallback(() => {
		setLoadingShared(true);
		fetch(`${hubApiUrl}/topics?type=strategy`)
			.then((res) => {
				if (!res.ok) throw new Error();
				return res.json();
			})
			.then((data) => {
				setSharedStrategies(data);
				setLoadingShared(false);
			})
			.catch(() => {
				toast.error(
					t("community:community.loadFailed", "Failed to load community ideas"),
				);
				setLoadingShared(false);
			});
	}, [t, hubApiUrl]);

	const fetchDiscussions = React.useCallback(() => {
		setLoadingDiscussions(true);
		fetch(`${hubApiUrl}/topics?type=discussion`)
			.then((res) => {
				if (!res.ok) throw new Error();
				return res.json();
			})
			.then((data) => {
				setDiscussions(data);
				setLoadingDiscussions(false);
			})
			.catch(() => {
				toast.error(
					t("community:discussion.loadFailed", "Failed to load discussions"),
				);
				setLoadingDiscussions(false);
			});
	}, [t, hubApiUrl]);

	useEffect(() => {
		fetchVerified();
		fetchNews();
		fetchSharedStrategies();
		fetchDiscussions();
	}, [fetchVerified, fetchNews, fetchSharedStrategies, fetchDiscussions]);

	// Fetch comments when a topic is selected
	useEffect(() => {
		if (selectedTopic) {
			setLoadingComments(true);
			fetch(`${hubApiUrl}/topics/${selectedTopic.id}/comments`)
				.then((res) => {
					if (!res.ok) throw new Error();
					return res.json();
				})
				.then((data) => {
					setComments(data);
					setLoadingComments(false);
				})
				.catch(() => {
					toast.error(
						t(
							"community:detailedView.commentFailed",
							"Failed to load comments",
						),
					);
					setLoadingComments(false);
				});
		}
	}, [selectedTopic, t, hubApiUrl]);

	// Fetch comments when a news item is selected
	useEffect(() => {
		if (selectedNews) {
			setLoadingNewsComments(true);
			fetch(`${hubApiUrl}/news/${selectedNews.id}/comments`)
				.then((res) => {
					if (!res.ok) throw new Error();
					return res.json();
				})
				.then((data) => {
					setNewsComments(data);
					setLoadingNewsComments(false);
				})
				.catch(() => {
					toast.error("Failed to load news comments");
					setLoadingNewsComments(false);
				});
		}
	}, [selectedNews, hubApiUrl]);

	// Actions
	const handleImport = (
		name: string,
		description: string,
		config: Record<string, unknown>,
	) => {
		if (!config) {
			toast.error(
				t(
					"community:verified.jsonInvalid",
					"No strategy configuration details available",
				),
			);
			return;
		}

		const payload = {
			name: name,
			description: description,
			config_data: config,
			symbol_selection_mode:
				(config.symbol_selection_mode as string) || ("STATIC" as const),
			symbols: config.symbol ? [config.symbol as string] : ["BTCUSDT"],
			use_ml_confirmation: (config.use_ml_confirmation as boolean) || false,
			foundation_weights:
				(config.foundation_weights as Record<string, unknown>) || null,
		};

		saveConfig.mutate(payload, {
			onSuccess: (data) => {
				toast.success(
					t(
						"community:detailedView.importSuccess",
						`Imported "${name}" successfully!`,
					),
					{
						description: t(
							"common:checkItOut",
							"Check it out in the editor or start a backtest.",
						),
					},
				);
				navigate(`/editor/${data.id}`);
			},
			onError: (err) => {
				toast.error(`${t("common:error")}: ${err.message}`);
			},
		});
	};

	const handleLike = async (topicId: string, e?: React.MouseEvent) => {
		if (e) e.stopPropagation();
		if (likedTopics.includes(topicId)) {
			toast.info(
				"You have already liked this topic.",
			);
			return;
		}

		try {
			const res = await fetch(`${hubApiUrl}/topics/${topicId}/like`, {
				method: "POST",
			});
			if (!res.ok) throw new Error();
			const updatedTopic = await res.json();

			// Save like status to local storage
			const updatedLiked = [...likedTopics, topicId];
			setLikedTopics(updatedLiked);
			localStorage.setItem(
				`depthsight_liked_topics_${username}`,
				JSON.stringify(updatedLiked),
			);

			// Update in lists
			setSharedStrategies((prev) =>
				prev.map((topicItem) =>
					topicItem.id === topicId ? updatedTopic : topicItem,
				),
			);
			setDiscussions((prev) =>
				prev.map((topicItem) =>
					topicItem.id === topicId ? updatedTopic : topicItem,
				),
			);
			if (selectedTopic && selectedTopic.id === topicId) {
				setSelectedTopic(updatedTopic);
			}
			toast.success(t("community:community.upvoted", "Upvoted!"));
		} catch {
			toast.error(t("community:community.loadFailed", "Failed to vote"));
		}
	};

	const handleToggleVerify = async (
		idea: HubTopicResponse,
		e?: React.MouseEvent,
	) => {
		if (e) e.stopPropagation();
		const action = idea.is_verified ? "unverify" : "verify";
		try {
			const res = await fetch(`${hubApiUrl}/topics/${idea.id}/${action}`, {
				method: "POST",
				headers: {
					Authorization: `Bearer ${adminKey}`,
				},
			});
			if (!res.ok) throw new Error();
			const updatedTopic = await res.json();

			// Update in lists
			setSharedStrategies((prev) =>
				prev.map((t) => (t.id === idea.id ? updatedTopic : t)),
			);
			setDiscussions((prev) =>
				prev.map((t) => (t.id === idea.id ? updatedTopic : t)),
			);

			// Update verified list
			if (action === "verify") {
				setVerifiedStrategies((prev) => {
					if (prev.some((t) => t.id === updatedTopic.id)) return prev;
					return [updatedTopic, ...prev];
				});
				toast.success("Added to presets!");
			} else {
				setVerifiedStrategies((prev) => prev.filter((t) => t.id !== idea.id));
				toast.success("Removed from presets!");
			}

			if (selectedTopic && selectedTopic.id === idea.id) {
				setSelectedTopic(updatedTopic);
			}
		} catch {
			toast.error(
				"Failed to toggle preset status",
			);
		}
	};

	const isDeletionAuthorized = (topicId: string) => {
		const storedTokens = JSON.parse(
			localStorage.getItem("depthsight_hub_tokens") || "{}",
		);
		const hasToken = !!storedTokens[topicId];
		const isAdmin = !!localStorage.getItem("depthsight_hub_admin_key");
		return hasToken || isAdmin;
	};

	const handleDeleteTopic = async (topicId: string, e?: React.MouseEvent) => {
		if (e) e.stopPropagation();
		if (
			!window.confirm(
				t(
					"community:detailedView.deleteConfirm",
					"Are you sure you want to delete this topic?",
				),
			)
		) {
			return;
		}

		try {
			const storedTokens = JSON.parse(
				localStorage.getItem("depthsight_hub_tokens") || "{}",
			);
			const userToken = storedTokens[topicId];
			const adminKey = localStorage.getItem("depthsight_hub_admin_key");

			let url = `${hubApiUrl}/topics/${topicId}`;
			const queryParams = new URLSearchParams();
			if (userToken) {
				queryParams.append("delete_token", userToken);
			} else if (adminKey) {
				queryParams.append("delete_token", adminKey);
			}

			if (queryParams.toString()) {
				url += `?${queryParams.toString()}`;
			}

			const headers: Record<string, string> = {};
			if (adminKey) {
				headers.Authorization = `Bearer ${adminKey}`;
			}

			const res = await fetch(url, {
				method: "DELETE",
				headers,
			});

			if (!res.ok) {
				const errData = await res.json().catch(() => ({}));
				throw new Error(errData.detail || "Failed to delete");
			}

			toast.success(
				t("community:detailedView.topicDeleted", "Topic deleted successfully!"),
			);

			if (userToken) {
				delete storedTokens[topicId];
				localStorage.setItem(
					"depthsight_hub_tokens",
					JSON.stringify(storedTokens),
				);
			}

			setSharedStrategies((prev) => prev.filter((t) => t.id !== topicId));
			setDiscussions((prev) => prev.filter((t) => t.id !== topicId));
			if (selectedTopic && selectedTopic.id === topicId) {
				setSelectedTopic(null);
			}
		} catch (error: unknown) {
			const err = error as Error;
			toast.error(`${t("common:error")}: ${err.message}`);
		}
	};

	const handleCommentSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!newCommentText.trim() || !selectedTopic) return;

		setSubmittingComment(true);
		try {
			const author = user?.username || "Anonymous";
			const headers: Record<string, string> = {
				"Content-Type": "application/json",
			};
			if (adminKey) {
				headers.Authorization = `Bearer ${adminKey}`;
			}
			const res = await fetch(
				`${hubApiUrl}/topics/${selectedTopic.id}/comments`,
				{
					method: "POST",
					headers,
					body: JSON.stringify({
						author_name: author,
						text: newCommentText.trim(),
					}),
				},
			);

			if (!res.ok) throw new Error();
			const newComment = await res.json();

			setComments((prev) => [...prev, newComment]);
			setNewCommentText("");
			setSelectedTopic((prev) =>
				prev
					? { ...prev, comments_count: (prev.comments_count || 0) + 1 }
					: null,
			);
			setSharedStrategies((prev) =>
				prev.map((t) =>
					t.id === selectedTopic.id
						? { ...t, comments_count: (t.comments_count || 0) + 1 }
						: t,
				),
			);
			setDiscussions((prev) =>
				prev.map((t) =>
					t.id === selectedTopic.id
						? { ...t, comments_count: (t.comments_count || 0) + 1 }
						: t,
				),
			);
			toast.success(
				t("community:detailedView.commentSuccess", "Comment posted!"),
			);
		} catch {
			toast.error(
				t("community:detailedView.commentFailed", "Failed to post comment"),
			);
		} finally {
			setSubmittingComment(false);
		}
	};

	const handleNewsCommentSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!newNewsCommentText.trim() || !selectedNews) return;

		setSubmittingNewsComment(true);
		try {
			const author = user?.username || "Anonymous";
			const headers: Record<string, string> = {
				"Content-Type": "application/json",
			};
			if (adminKey) {
				headers.Authorization = `Bearer ${adminKey}`;
			}
			const res = await fetch(`${hubApiUrl}/news/${selectedNews.id}/comments`, {
				method: "POST",
				headers,
				body: JSON.stringify({
					author_name: author,
					text: newNewsCommentText.trim(),
				}),
			});

			if (!res.ok) throw new Error();
			const newComment = await res.json();

			setNewsComments((prev) => [...prev, newComment]);
			setNewNewsCommentText("");
			setSelectedNews((prev) =>
				prev
					? { ...prev, comments_count: (prev.comments_count || 0) + 1 }
					: null,
			);
			setNews((prev) =>
				prev.map((n) =>
					n.id === selectedNews.id
						? { ...n, comments_count: (n.comments_count || 0) + 1 }
						: n,
				),
			);
			toast.success("Comment posted!");
		} catch {
			toast.error("Failed to post comment");
		} finally {
			setSubmittingNewsComment(false);
		}
	};

	const handleNewsLike = async (newsId: number, e?: React.MouseEvent) => {
		if (e) e.stopPropagation();
		if (likedNews.includes(newsId)) {
			toast.info(
				"You have already liked this news.",
			);
			return;
		}

		try {
			const res = await fetch(`${hubApiUrl}/news/${newsId}/like`, {
				method: "POST",
			});
			if (!res.ok) throw new Error();
			const updatedNews = await res.json();

			// Save like status to local storage
			const updatedLiked = [...likedNews, newsId];
			setLikedNews(updatedLiked);
			localStorage.setItem(
				`depthsight_liked_news_${username}`,
				JSON.stringify(updatedLiked),
			);

			setNews((prev) => prev.map((n) => (n.id === newsId ? updatedNews : n)));
			if (selectedNews && selectedNews.id === newsId) {
				setSelectedNews(updatedNews);
			}
			toast.success("Liked news!");
		} catch {
			toast.error("Failed to like news");
		}
	};

	const handleCreateTopic = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!newTopicTitle.trim() || !newTopicDesc.trim()) {
			toast.error(
				t("common:validation.fillAllFields", "Please fill in all fields"),
			);
			return;
		}

		setPublishingTopic(true);
		try {
			const author = user?.username || "Anonymous";
			const headers: Record<string, string> = {
				"Content-Type": "application/json",
			};
			if (adminKey) {
				headers.Authorization = `Bearer ${adminKey}`;
			}
			const res = await fetch(`${hubApiUrl}/topics`, {
				method: "POST",
				headers,
				body: JSON.stringify({
					topic_type: "discussion",
					title: newTopicTitle.trim(),
					description: newTopicDesc.trim(),
					author_name: author,
				}),
			});

			if (!res.ok) throw new Error();

			const newTopic = await res.json();
			const deleteToken = newTopic.delete_token;
			if (deleteToken) {
				const storedTokens = JSON.parse(
					localStorage.getItem("depthsight_hub_tokens") || "{}",
				);
				storedTokens[newTopic.id] = deleteToken;
				localStorage.setItem(
					"depthsight_hub_tokens",
					JSON.stringify(storedTokens),
				);
			}

			toast.success(
				t("community:createTopic.success", "Discussion topic published!"),
			);
			setNewTopicTitle("");
			setNewTopicDesc("");
			setIsCreateDialogOpen(false);
			fetchDiscussions();
		} catch {
			toast.error(t("community:createTopic.failed", "Failed to publish topic"));
		} finally {
			setPublishingTopic(false);
		}
	};

	const handleCreateNewsItem = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!newsTitle.trim() || !newsText.trim()) {
			toast.error(
				t("common:validation.fillAllFields", "Please fill in all fields"),
			);
			return;
		}

		setPublishingNews(true);
		try {
			const headers: Record<string, string> = {
				"Content-Type": "application/json",
			};
			if (adminKey) {
				headers.Authorization = `Bearer ${adminKey}`;
			}

			const today = new Date().toISOString().split("T")[0];

			const res = await fetch(`${hubApiUrl}/news`, {
				method: "POST",
				headers,
				body: JSON.stringify({
					title: newsTitle.trim(),
					text: newsText.trim(),
					date: today,
				}),
			});

			if (!res.ok) {
				const errData = await res.json().catch(() => ({}));
				throw new Error(errData.detail || "Failed to publish news");
			}

			toast.success(
				t("community:addNews.addSuccess", "News item successfully published!"),
			);
			setNewsTitle("");
			setNewsText("");
			setIsAddNewsOpen(false);
			fetchNews();
		} catch (error: unknown) {
			const err = error as Error;
			toast.error(`${t("common:error")}: ${err.message}`);
		} finally {
			setPublishingNews(false);
		}
	};

	const handleDeleteNewsItem = async (newsId: number, e?: React.MouseEvent) => {
		if (e) e.stopPropagation();
		if (
			!window.confirm(
				t(
					"community:addNews.deleteConfirm",
					"Are you sure you want to delete this news item?",
				),
			)
		) {
			return;
		}

		try {
			const headers: Record<string, string> = {};
			if (adminKey) {
				headers.Authorization = `Bearer ${adminKey}`;
			}

			const res = await fetch(`${hubApiUrl}/news/${newsId}`, {
				method: "DELETE",
				headers,
			});

			if (!res.ok) {
				const errData = await res.json().catch(() => ({}));
				throw new Error(errData.detail || "Failed to delete news item");
			}

			toast.success(
				t("community:addNews.deleteSuccess", "News item deleted successfully!"),
			);
			fetchNews();
		} catch (error: unknown) {
			const err = error as Error;
			toast.error(`${t("common:error")}: ${err.message}`);
		}
	};

	const handleTogglePinNewsItem = async (newsId: number, pin: boolean, e?: React.MouseEvent) => {
		if (e) e.stopPropagation();

		try {
			const headers: Record<string, string> = {};
			if (adminKey) {
				headers.Authorization = `Bearer ${adminKey}`;
			}

			const endpoint = pin ? "pin" : "unpin";
			const res = await fetch(`${hubApiUrl}/news/${newsId}/${endpoint}`, {
				method: "POST",
				headers,
			});

			if (!res.ok) {
				const errData = await res.json().catch(() => ({}));
				throw new Error(errData.detail || `Failed to ${endpoint} news item`);
			}

			toast.success(
				pin
					? t("community:news.pinSuccess", "News item pinned successfully!")
					: t("community:news.unpinSuccess", "News item unpinned successfully!"),
			);
			fetchNews();
		} catch (error: unknown) {
			const err = error as Error;
			toast.error(`${t("common:error")}: ${err.message}`);
		}
	};

	const handleFeedbackSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!feedbackText.trim()) {
			toast.error(
				t("community:feedback.placeholder", "Please enter a feedback message."),
			);
			return;
		}

		setSubmittingFeedback(true);
		try {
			const res = await fetch(`${hubApiUrl}/feedback`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					category,
					text: feedbackText,
					contact_email: contactEmail || undefined,
				}),
			});

			if (!res.ok) throw new Error();

			const data = await res.json().catch(() => ({}));
			if (data.ticket_id) {
				const newTicket = {
					id: data.ticket_id,
					category: category,
					text: feedbackText,
					createdAt: new Date().toISOString(),
				};
				const updated = [newTicket, ...localFeedbackTickets];
				setLocalFeedbackTickets(updated);
				localStorage.setItem(
					"depthsight_hub_feedback_tickets",
					JSON.stringify(updated),
				);
			}

			toast.success(
				t(
					"community:feedback.successToast",
					"Feedback sent to DepthSight developers!",
				),
				{
					description: t(
						"community:feedback.successDesc",
						"Thank you for helping us improve DepthSight.",
					),
				},
			);
			setFeedbackText("");
			setContactEmail("");
		} catch {
			toast.error(
				t("community:feedback.failedToast", "Feedback submission failed."),
			);
		} finally {
			setSubmittingFeedback(false);
		}
	};

	const handleHubReplyFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		const file = e.target.files?.[0];
		if (file) {
			if (file.size > 5 * 1024 * 1024) {
				toast.error(
					t("common:errors.fileTooLarge", "File too large (max 5MB)"),
				);
				return;
			}
			const reader = new FileReader();
			reader.onloadend = () => {
				setNewHubImage(reader.result as string);
			};
			reader.readAsDataURL(file);
		}
	};

	const handleSendHubReply = async (e: React.FormEvent) => {
		e.preventDefault();
		if ((!newHubReply.trim() && !newHubImage) || !selectedHubTicket) return;

		setSubmittingHubReply(true);
		try {
			const res = await fetch(
				`${hubApiUrl}/tickets/${selectedHubTicket.id}/messages`,
				{
					method: "POST",
					headers: {
						"Content-Type": "application/json",
					},
					body: JSON.stringify({
						text: newHubReply.trim(),
						image: newHubImage || undefined,
						sender_name: t("community:hubTicket.you", "User"),
					}),
				},
			);

			if (!res.ok) throw new Error();

			const newMsg = await res.json();
			setHubTicketMessages((prev) => [...prev, newMsg]);
			setNewHubReply("");
			setNewHubImage(null);
			setHubTicketStatus("OPEN"); // Reopen automatically on user reply
		} catch {
			toast.error(t("common:errorLoadingData", "Failed to send message"));
		} finally {
			setSubmittingHubReply(false);
		}
	};

	const handleCloseHubTicket = async () => {
		if (!selectedHubTicket) return;

		setUpdatingHubStatus(true);
		try {
			const res = await fetch(
				`${hubApiUrl}/tickets/${selectedHubTicket.id}/status`,
				{
					method: "PATCH",
					headers: {
						"Content-Type": "application/json",
					},
					body: JSON.stringify({
						status: "CLOSED",
					}),
				},
			);

			if (!res.ok) throw new Error();

			const data = await res.json();
			setHubTicketStatus(data.status);
			toast.success(
				t("community:hubTicket.ticketClosed", "Ticket closed successfully"),
			);
		} catch {
			toast.error(t("common:errorLoadingData", "Failed to close ticket"));
		} finally {
			setUpdatingHubStatus(false);
		}
	};

	return (
		<div className="min-h-screen bg-background text-foreground pb-20">
			{/* Banner Hero */}
			<section className="relative overflow-hidden pt-12 pb-16 px-4 border-b border-border/40 bg-black/20">
				<div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(120,119,198,0.15),rgba(255,255,255,0))]" />
				<div className="max-w-5xl mx-auto text-center relative z-10 space-y-4">
					<motion.div
						initial={{ scale: 0.8, opacity: 0 }}
						animate={{ scale: 1, opacity: 1 }}
						transition={{ duration: 0.5 }}
						className="inline-flex items-center justify-center p-3 mb-2 rounded-2xl bg-primary/10 text-primary border border-primary/20"
					>
						<Globe className="w-7 h-7" />
					</motion.div>
					<motion.h1
						initial={{ y: 15, opacity: 0 }}
						animate={{ y: 0, opacity: 1 }}
						className="text-4xl md:text-5xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-foreground via-foreground/90 to-primary"
					>
						{t("community:title", "Discovery Hub")}
					</motion.h1>
					<motion.p
						initial={{ y: 15, opacity: 0 }}
						animate={{ y: 0, opacity: 1 }}
						transition={{ delay: 0.1 }}
						className="text-muted-foreground max-w-xl mx-auto text-sm md:text-base"
					>
						{t("community:description")}
					</motion.p>
				</div>
			</section>

			{/* Main Layout Grid */}
			<div className="max-w-[1600px] mx-auto px-4 mt-8 grid grid-cols-1 lg:grid-cols-4 gap-8">
				{/* Left Columns (3/4 width on large screens) */}
				<div className="lg:col-span-3 space-y-6">
					{/* Navigation Tabs */}
					<Tabs
						value={activeTab}
						onValueChange={setActiveTab}
						className="w-full"
					>
						<div className="flex justify-between items-center border-b border-border/40 pb-2">
							<TabsList className="bg-muted/50 border border-border/20">
								<TabsTrigger
									value="verified"
									className="gap-2 text-xs md:text-sm"
								>
									<Sparkles className="w-3.5 h-3.5" />
									{t("community:tabs.verified", "Verified Templates")}
								</TabsTrigger>
								<TabsTrigger
									value="community"
									className="gap-2 text-xs md:text-sm"
								>
									<TrendingUp className="w-3.5 h-3.5" />
									{t("community:tabs.community", "Trading Ideas")}
								</TabsTrigger>
								<TabsTrigger
									value="discussion"
									className="gap-2 text-xs md:text-sm"
								>
									<MessageSquare className="w-3.5 h-3.5" />
									{t("community:tabs.discussion", "Discussions")}
								</TabsTrigger>
								<TabsTrigger
									value="network"
									className="gap-2 text-xs md:text-sm"
								>
									<Network className="w-3.5 h-3.5" />
									{t("community:tabs.network", "Network Status")}
								</TabsTrigger>
							</TabsList>

							<div className="flex items-center gap-2">
								<Button
									size="sm"
									variant="ghost"
									className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
									onClick={() => {
										const currentKey =
											localStorage.getItem("depthsight_hub_admin_key") || "";
										const newKey = window.prompt(
											t("community:admin.adminKeyPrompt"),
											currentKey,
										);
										if (newKey !== null) {
											if (newKey.trim()) {
												localStorage.setItem(
													"depthsight_hub_admin_key",
													newKey.trim(),
												);
												setAdminKey(newKey.trim());
												toast.success(t("community:admin.moderatorActivated"));
											} else {
												localStorage.removeItem("depthsight_hub_admin_key");
												setAdminKey(null);
												toast.success(t("community:admin.moderatorDisabled"));
											}
											setSharedStrategies((prev) => [...prev]);
											setDiscussions((prev) => [...prev]);
										}
									}}
									title={t("community:admin.moderatorSettings")}
								>
									<Settings className="w-4 h-4" />
								</Button>

								{activeTab === "discussion" && (
									<Button
										size="sm"
										className="h-8 gap-1.5 text-xs"
										onClick={() => setIsCreateDialogOpen(true)}
									>
										<Plus className="w-3.5 h-3.5" />
										{t("community:admin.createTopic", "Create Topic")}
									</Button>
								)}
							</div>
						</div>

						{/* Verified Templates Tab */}
						<TabsContent value="verified" className="mt-6">
							{loadingVerified ? (
								<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
									{[1, 2].map((i) => (
										<Card
											key={i}
											className="animate-pulse bg-card/40 border-border/20 h-48"
										/>
									))}
								</div>
							) : verifiedStrategies.length > 0 ? (
								<>
									<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
										{verifiedStrategies
											.slice(
												(verifiedPage - 1) * PRESETS_PER_PAGE,
												verifiedPage * PRESETS_PER_PAGE,
											)
											.map((strategy, idx) => (
												<motion.div
													key={strategy.id}
													initial={{ opacity: 0, y: 15 }}
													animate={{ opacity: 1, y: 0 }}
													transition={{ delay: idx * 0.05 }}
													onClick={() => setSelectedTopic(strategy)}
													className="cursor-pointer"
												>
													<Card className="h-full border border-border/30 hover:border-primary/30 bg-card/30 hover:bg-card/60 transition-all duration-300 hover:shadow-lg flex flex-col justify-between overflow-hidden relative group">
														<div className="absolute top-0 left-0 w-1 h-full bg-primary/20 group-hover:bg-primary/50 transition-colors" />
														<CardHeader className="pb-2">
															<div className="flex justify-between items-start">
																<CardTitle className="text-base font-bold text-foreground/90">
																	{getTopicTitle(strategy, t)}
																</CardTitle>
																<Badge
																	variant="secondary"
																	className="text-[10px] scale-90 px-2"
																>
																	{t(
																		"community:verified.officialBadge",
																		"Official",
																	)}
																</Badge>
															</div>
															<CardDescription className="line-clamp-3 text-xs pt-1">
																{strategy.description}
															</CardDescription>
														</CardHeader>
														<CardContent className="pb-2">
															{strategy.tags &&
																Array.isArray(strategy.tags) &&
																strategy.tags.length > 0 && (
																	<div className="flex flex-wrap gap-1 pt-2">
																		{strategy.tags.map((tag) => (
																			<Badge
																				key={tag}
																				variant="outline"
																				className="text-[9px] px-1.5 py-0"
																			>
																				{tag}
																			</Badge>
																		))}
																	</div>
																)}
														</CardContent>
														<CardFooter className="pt-2 border-t border-border/10 bg-black/10 flex gap-2">
															<Button
																className="flex-1 gap-2 text-xs h-8"
																variant="secondary"
																onClick={(e) => {
																	e.stopPropagation();
																	handleImport(
																		getTopicTitle(strategy, t),
																		strategy.description,
																		strategy.strategy_json,
																	);
																}}
																disabled={saveConfig.isPending}
															>
																<Download className="w-3.5 h-3.5" />
																{t(
																	"community:verified.importConfig",
																	"Import Configuration",
																)}
															</Button>
															{adminKey && strategy.id !== undefined && (
																<Button
																	variant="outline"
																	size="icon"
																	className="h-8 w-8 text-muted-foreground hover:text-red-500 border-border/40 hover:border-red-500/40"
																	onClick={(e) => {
																		e.stopPropagation();
																		handleToggleVerify(strategy, e);
																	}}
																	title={t(
																		"community:verified.deletePreset",
																		"Delete preset",
																	)}
																>
																	<Trash2 className="w-3.5 h-3.5" />
																</Button>
															)}
														</CardFooter>
													</Card>
												</motion.div>
											))}
									</div>
									{verifiedStrategies.length > PRESETS_PER_PAGE && (
										<div className="flex justify-center items-center gap-4 mt-6">
											<Button
												variant="outline"
												size="icon"
												className="h-8 w-8"
												disabled={verifiedPage === 1}
												onClick={() =>
													setVerifiedPage((prev) => Math.max(prev - 1, 1))
												}
											>
												<ChevronLeft className="w-4 h-4" />
											</Button>
											<span className="text-xs text-muted-foreground font-mono">
												{verifiedPage} /{" "}
												{Math.ceil(
													verifiedStrategies.length / PRESETS_PER_PAGE,
												)}
											</span>
											<Button
												variant="outline"
												size="icon"
												className="h-8 w-8"
												disabled={
													verifiedPage ===
													Math.ceil(
														verifiedStrategies.length / PRESETS_PER_PAGE,
													)
												}
												onClick={() =>
													setVerifiedPage((prev) =>
														Math.min(
															prev + 1,
															Math.ceil(
																verifiedStrategies.length / PRESETS_PER_PAGE,
															),
														),
													)
												}
											>
												<ChevronRight className="w-4 h-4" />
											</Button>
										</div>
									)}
								</>
							) : (
								<div className="text-center py-16 bg-card/20 rounded-2xl border border-dashed border-border/40">
									<BookOpen className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
									<p className="text-muted-foreground text-sm">
										{t(
											"community:verified.noTemplates",
											"No strategy templates found.",
										)}
									</p>
								</div>
							)}
						</TabsContent>

						{/* Shared Strategies / Trading Ideas Tab */}
						<TabsContent value="community" className="mt-6">
							{loadingShared ? (
								<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
									{[1, 2].map((i) => (
										<Card
											key={i}
											className="animate-pulse bg-card/40 border-border/20 h-52"
										/>
									))}
								</div>
							) : sharedStrategies.length > 0 ? (
								<>
									<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
										{sharedStrategies
											.slice(
												(communityPage - 1) * COMMUNITY_PER_PAGE,
												communityPage * COMMUNITY_PER_PAGE,
											)
											.map((idea, idx) => {
												const pnl = idea.kpis?.total_pnl || 0;
												const isPnlPositive = pnl >= 0;

												return (
													<motion.div
														key={idea.id}
														initial={{ opacity: 0, y: 15 }}
														animate={{ opacity: 1, y: 0 }}
														transition={{ delay: idx * 0.05 }}
														onClick={() => setSelectedTopic(idea)}
													>
														<Card className="h-full border border-border/30 hover:border-primary/40 bg-card/20 hover:bg-card/40 transition-all duration-300 hover:shadow-lg cursor-pointer flex flex-col justify-between overflow-hidden relative group">
															<CardHeader className="pb-2">
																<div className="flex justify-between items-start">
																	<div className="space-y-1">
																		<Badge
																			variant="outline"
																			className="text-[9px] uppercase border-primary/20 text-primary px-1.5 py-0"
																		>
																			{idea.symbol || "Global"}
																		</Badge>
																		<CardTitle className="text-base font-bold text-foreground/90 group-hover:text-primary transition-colors">
																			{getTopicTitle(idea, t)}
																		</CardTitle>
																	</div>
																	<span className={cn("text-[10px] text-muted-foreground flex items-center gap-1", idea.is_admin && "text-purple-400 font-bold")}>
																		<UserIcon className={cn("w-3 h-3", idea.is_admin && "text-purple-400")} />
																		{idea.author_name}
																		{idea.is_admin && (
																			<Badge
																				variant="outline"
																				className="text-[8px] h-3.5 border-purple-500/30 text-purple-400 bg-purple-500/5 px-1 py-0 uppercase tracking-wide shrink-0"
																			>
																				{isRu ? "Админ" : "Admin"}
																			</Badge>
																		)}
																	</span>
																</div>
																<CardDescription className="line-clamp-2 text-xs pt-1">
																	{idea.description}
																</CardDescription>
															</CardHeader>

															<CardContent className="pb-3 space-y-3">
																{/* Mini KPIs badges */}
																<div className="grid grid-cols-4 gap-2 text-center bg-black/20 p-2 rounded-lg border border-border/10">
																	<div>
																		<div className="text-[9px] text-muted-foreground uppercase">
																			{t("community:community.pnl", "PnL")}
																		</div>
																		<div
																			className={`text-xs font-bold ${isPnlPositive ? "text-green-500" : "text-red-500"}`}
																		>
																			{isPnlPositive ? "+" : "-"}$
																			{Math.abs(pnl).toFixed(2)}
																		</div>
																	</div>
																	<div>
																		<div className="text-[9px] text-muted-foreground uppercase">
																			WinRate
																		</div>
																		<div className="text-xs font-bold text-foreground">
																			{(idea.kpis?.win_rate || 0).toFixed(1)}%
																		</div>
																	</div>
																	<div>
																		<div className="text-[9px] text-muted-foreground uppercase">
																			Drawdown
																		</div>
																		<div className="text-xs font-bold text-foreground">
																			{(idea.kpis?.max_drawdown || 0).toFixed(
																				2,
																			)}
																			%
																		</div>
																	</div>
																	<div>
																		<div className="text-[9px] text-muted-foreground uppercase">
																			{t(
																				"community:community.trades",
																				"Trades",
																			)}
																		</div>
																		<div className="text-xs font-bold text-foreground">
																			{idea.kpis?.trades || 0}
																		</div>
																	</div>
																</div>

																{/* Sparkline curve */}
																{idea.equity_curve &&
																	idea.equity_curve.length > 0 && (
																		<MiniEquityChart data={idea.equity_curve} />
																	)}
															</CardContent>

															<CardFooter className="pt-2 pb-2.5 px-4 border-t border-border/10 bg-black/15 flex justify-between items-center text-xs">
																<div className="flex gap-4">
																	<button
																		className={cn(
																			"flex items-center gap-1 transition-colors",
																			likedTopics.includes(idea.id)
																				? "text-primary font-bold cursor-default"
																				: "text-muted-foreground hover:text-primary",
																		)}
																		onClick={(e) => handleLike(idea.id, e)}
																	>
																		<ThumbsUp
																			className={cn(
																				"w-3.5 h-3.5",
																				likedTopics.includes(idea.id) &&
																					"fill-primary/20",
																			)}
																		/>
																		<span>{idea.likes_count}</span>
																	</button>
																	<div className="flex items-center gap-1 text-muted-foreground">
																		<MessageSquare className="w-3.5 h-3.5" />
																		<span>{idea.comments_count || 0}</span>
																	</div>
																	{adminKey && (
																		<button
																			className={`flex items-center gap-1 transition-colors ${idea.is_verified ? "text-yellow-500 hover:text-yellow-600" : "text-muted-foreground hover:text-yellow-500"}`}
																			onClick={(e) => {
																				e.stopPropagation();
																				handleToggleVerify(idea, e);
																			}}
																			title={
																				idea.is_verified
																					? "Remove from presets"
																					: "Add to presets"
																			}
																		>
																			<Sparkles className="w-3.5 h-3.5" />
																			<span>
																				{idea.is_verified
																					? "In Presets"
																					: "To Presets"}
																			</span>
																		</button>
																	)}
																	{isDeletionAuthorized(idea.id) && (
																		<button
																			className="flex items-center gap-1 text-muted-foreground hover:text-red-500 transition-colors"
																			onClick={(e) =>
																				handleDeleteTopic(idea.id, e)
																			}
																			title={t(
																				"community:community.deletePublication",
																				"Delete publication",
																			)}
																		>
																			<Trash2 className="w-3.5 h-3.5" />
																		</button>
																	)}
																</div>

																<span className="text-primary group-hover:translate-x-1 transition-transform flex items-center gap-1 font-medium text-[11px]">
																	{t("community:community.inspect", "Inspect")}
																	<ArrowRight className="w-3 h-3" />
																</span>
															</CardFooter>
														</Card>
													</motion.div>
												);
											})}
									</div>
									{sharedStrategies.length > COMMUNITY_PER_PAGE && (
										<div className="flex justify-center items-center gap-4 mt-6">
											<Button
												variant="outline"
												size="icon"
												className="h-8 w-8"
												disabled={communityPage === 1}
												onClick={() =>
													setCommunityPage((prev) => Math.max(prev - 1, 1))
												}
											>
												<ChevronLeft className="w-4 h-4" />
											</Button>
											<span className="text-xs text-muted-foreground font-mono">
												{communityPage} /{" "}
												{Math.ceil(
													sharedStrategies.length / COMMUNITY_PER_PAGE,
												)}
											</span>
											<Button
												variant="outline"
												size="icon"
												className="h-8 w-8"
												disabled={
													communityPage ===
													Math.ceil(
														sharedStrategies.length / COMMUNITY_PER_PAGE,
													)
												}
												onClick={() =>
													setCommunityPage((prev) =>
														Math.min(
															prev + 1,
															Math.ceil(
																sharedStrategies.length / COMMUNITY_PER_PAGE,
															),
														),
													)
												}
											>
												<ChevronRight className="w-4 h-4" />
											</Button>
										</div>
									)}
								</>
							) : (
								<div className="text-center py-16 bg-card/20 rounded-2xl border border-dashed border-border/40">
									<BookOpen className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
									<p className="text-muted-foreground text-sm">
										{t(
											"community:community.noIdeas",
											"No trading ideas found.",
										)}
									</p>
								</div>
							)}
						</TabsContent>

						{/* Discussions Tab */}
						<TabsContent value="discussion" className="mt-6">
							{loadingDiscussions ? (
								<div className="space-y-3">
									{[1, 2].map((i) => (
										<div
											key={i}
											className="h-16 animate-pulse bg-card/40 rounded-xl border border-border/20"
										/>
									))}
								</div>
							) : discussions.length > 0 ? (
								<div className="space-y-3">
									{discussions.map((topic, idx) => (
										<motion.div
											key={topic.id}
											initial={{ opacity: 0, x: -10 }}
											animate={{ opacity: 1, x: 0 }}
											transition={{ delay: idx * 0.05 }}
											onClick={() => setSelectedTopic(topic)}
										>
											<div className="p-4 rounded-xl border border-border/30 bg-card/20 hover:bg-card/40 transition-all duration-200 hover:shadow cursor-pointer flex justify-between items-center group">
												<div className="space-y-1 pr-4">
													<h4 className="text-sm md:text-base font-semibold group-hover:text-primary transition-colors">
														{topic.title}
													</h4>
													<div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
														<span className={cn("flex items-center gap-1", topic.is_admin && "text-purple-400 font-bold")}>
															<UserIcon className={cn("w-3 h-3", topic.is_admin && "text-purple-400")} />
															{topic.author_name}
															{topic.is_admin && (
																<Badge
																	variant="outline"
																	className="text-[8px] h-3.5 border-purple-500/30 text-purple-400 bg-purple-500/5 px-1 py-0 uppercase tracking-wide shrink-0"
																>
																	{isRu ? "Админ" : "Admin"}
																</Badge>
															)}
														</span>
														<span className="flex items-center gap-1">
															<Calendar className="w-3 h-3" />
															{new Date(topic.created_at).toLocaleDateString(
																isRu ? "ru-RU" : "en-US",
															)}
														</span>
													</div>
												</div>

												<div className="flex items-center gap-4 text-xs text-muted-foreground">
													<button
														className={cn(
															"flex items-center gap-1.5 transition-colors p-1",
															likedTopics.includes(topic.id)
																? "text-primary font-bold cursor-default"
																: "hover:text-primary",
														)}
														onClick={(e) => handleLike(topic.id, e)}
													>
														<ThumbsUp
															className={cn(
																"w-3.5 h-3.5",
																likedTopics.includes(topic.id) &&
																	"fill-primary/20",
															)}
														/>
														<span>{topic.likes_count}</span>
													</button>
													<div className="flex items-center gap-1.5 text-muted-foreground p-1">
														<MessageSquare className="w-3.5 h-3.5" />
														<span>{topic.comments_count || 0}</span>
													</div>
													{isDeletionAuthorized(topic.id) && (
														<button
															className="flex items-center gap-1 hover:text-red-500 transition-colors p-1"
															onClick={(e) => handleDeleteTopic(topic.id, e)}
															title={t(
																"community:discussion.deleteTopic",
																"Delete topic",
															)}
														>
															<Trash2 className="w-3.5 h-3.5" />
														</button>
													)}
													<span className="group-hover:translate-x-1 transition-transform">
														<ChevronRight className="w-4 h-4 text-muted-foreground" />
													</span>
												</div>
											</div>
										</motion.div>
									))}
								</div>
							) : (
								<div className="text-center py-16 bg-card/20 rounded-2xl border border-dashed border-border/40">
									<MessageSquare className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
									<p className="text-muted-foreground text-sm">
										{t(
											"community:discussion.noDiscussions",
											"No active discussion topics.",
										)}
									</p>
								</div>
							)}
						</TabsContent>

						{/* Network Status Tab */}
						<TabsContent value="network" className="mt-6 space-y-6">
							{/* Statistics Grid */}
							<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
								<Card className="border border-border/30 bg-card/20 backdrop-blur-sm">
									<CardHeader className="p-4 pb-1">
										<CardDescription className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
											<Network className="w-3.5 h-3.5 text-blue-500" />
											{t("community:network.activeNodes", "Active Nodes")}
										</CardDescription>
									</CardHeader>
									<CardContent className="p-4 pt-1 pb-3">
										<div className="text-xl md:text-2xl font-mono font-bold text-foreground">
											{activeNodes.length > 0 ? activeNodes.length : "1"}
										</div>
										<p className="text-[9px] text-green-550 font-mono mt-0.5">
											▲ +{activeNodes.filter((n) => !n.is_master).length}{" "}
											{t("community:network.thisHour", "this hour")}
										</p>
									</CardContent>
								</Card>

								<Card className="border border-border/30 bg-card/20 backdrop-blur-sm">
									<CardHeader className="p-4 pb-1">
										<CardDescription className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
											<Clock className="w-3.5 h-3.5 text-emerald-400" />
											{t("community:network.avgLatency", "Average Latency")}
										</CardDescription>
									</CardHeader>
									<CardContent className="p-4 pt-1 pb-3">
										<div className="text-xl md:text-2xl font-mono font-bold text-foreground">
											{avgLatency}ms
										</div>
										<p className="text-[9px] text-muted-foreground font-mono mt-0.5">
											{t(
												"community:network.optimizedRouting",
												"Optimized routing",
											)}
										</p>
									</CardContent>
								</Card>

								<Card className="border border-border/30 bg-card/20 backdrop-blur-sm">
									<CardHeader className="p-4 pb-1">
										<CardDescription className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
											<Cpu className="w-3.5 h-3.5 text-indigo-400" />
											{t("community:network.uptimeSla", "Uptime SLA")}
										</CardDescription>
									</CardHeader>
									<CardContent className="p-4 pt-1 pb-3">
										<div className="text-xl md:text-2xl font-mono font-bold text-foreground">
											99.99%
										</div>
										<p className="text-[9px] text-green-550 font-mono mt-0.5">
											{t(
												"community:network.consensusVerified",
												"Consensus verified",
											)}
										</p>
									</CardContent>
								</Card>

								<Card className="border border-border/30 bg-card/20 backdrop-blur-sm">
									<CardHeader className="p-4 pb-1">
										<CardDescription className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
											<Activity className="w-3.5 h-3.5 text-primary" />
											{t("community:network.relayStatus", "Relay Status")}
										</CardDescription>
									</CardHeader>
									<CardContent className="p-4 pt-1 pb-3">
										<div className="text-xl md:text-2xl font-mono font-bold text-green-500 flex items-center gap-1.5">
											<span className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" />
											{t("community:network.connected", "CONNECTED")}
										</div>
										<p className="text-[9px] text-muted-foreground font-mono mt-0.5">
											SSL SHA-256 Validated
										</p>
									</CardContent>
								</Card>
							</div>

							{/* Node Map Canvas container */}
							<Card className="border border-border/30 bg-card/25 backdrop-blur-sm overflow-hidden">
								<CardHeader className="pb-3 border-b border-border/10">
									<div className="flex justify-between items-center gap-4">
										<CardTitle className="text-sm font-bold font-mono tracking-wider text-foreground/90 uppercase flex items-center gap-2">
											<Activity className="w-4 h-4 text-green-500 animate-pulse" />
											{t("community:network.topologyTitle")}
										</CardTitle>
										<div className="text-[10px] font-mono text-muted-foreground flex items-center gap-3">
											<span className="flex items-center gap-1.5">
												<span className="w-2 h-2 rounded-full bg-blue-500" />
												{t("community:network.masterHub")}
											</span>
											<span className="flex items-center gap-1.5">
												<span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
												{t("community:network.federatedNode")}
											</span>
										</div>
									</div>
								</CardHeader>
								<CardContent className="p-0 relative bg-black/40">
									<div className="relative overflow-hidden h-[650px] w-full">
										<NetworkMap activeNodes={activeNodes} isRu={isRu} t={t} />
									</div>
								</CardContent>
							</Card>
						</TabsContent>
					</Tabs>
				</div>

				{/* Right Column (1/4 width on large screens) */}
				<div className="space-y-6">
					{/* News Feed */}
					<div className="space-y-4">
						<div className="flex justify-between items-center pb-2 border-b border-border/40">
							<div className="flex items-center gap-2">
								<Newspaper className="w-4.5 h-4.5 text-primary" />
								<h3 className="text-base font-bold">
									{t("community:news.title", "News & Releases")}
								</h3>
							</div>
							{adminKey && (
								<Button
									size="sm"
									variant="ghost"
									className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
									onClick={() => setIsAddNewsOpen(true)}
									title={t("community:admin.addNews")}
								>
									<Plus className="w-4 h-4" />
								</Button>
							)}
						</div>
						{loadingNews ? (
							<div className="space-y-2">
								{[1, 2].map((i) => (
									<div
										key={i}
										className="h-20 animate-pulse bg-card/30 rounded-lg"
									/>
								))}
							</div>
						) : news.length > 0 ? (
							(() => {
								const pinnedNews = news.filter((item) => item.is_pinned);
								const regularNews = news.filter((item) => !item.is_pinned);

								return (
									<>
										<div className="space-y-3">
											{/* Pinned News */}
											{pinnedNews.map((item, idx) => (
												<motion.div
													key={item.id}
													initial={{ opacity: 0, x: 10 }}
													animate={{ opacity: 1, x: 0 }}
													transition={{ delay: idx * 0.05 }}
													onClick={() => setSelectedNews(item)}
													className="p-3.5 rounded-lg border border-primary/40 bg-primary/5 hover:bg-primary/10 transition-colors cursor-pointer space-y-1.5 group animate-fadeIn relative overflow-hidden"
												>
													<div className="absolute top-0 left-0 bottom-0 w-[3px] bg-primary" />
													<div className="flex justify-between items-center gap-2 pl-1.5">
														<div className="flex items-center gap-1.5 min-w-0 flex-1">
															<Pin className="w-3.5 h-3.5 text-primary shrink-0 rotate-45" />
															<h4 className="text-xs font-bold text-foreground/90 group-hover:text-primary transition-colors line-clamp-1">
																{item.title}
															</h4>
															<Badge
																variant="outline"
																className="text-[8px] h-4 border-primary/30 text-primary bg-primary/5 px-1 py-0 uppercase tracking-wide shrink-0"
															>
																{isRu ? "Закреплено" : "Pinned"}
															</Badge>
														</div>
														<div className="flex items-center gap-1.5 shrink-0">
															<span className="text-[8px] text-muted-foreground font-mono">
																{item.date}
															</span>
															{adminKey && item.id !== undefined && (
																<div className="flex items-center gap-1">
																	<button
																		className="text-primary hover:text-primary/80 transition-colors p-0.5"
																		onClick={(e) => {
																			e.stopPropagation();
																			handleTogglePinNewsItem(item.id!, false, e);
																		}}
																		title={isRu ? "Открепить" : "Unpin"}
																	>
																		<Pin className="w-3 h-3 rotate-45" />
																	</button>
																	<button
																		className="text-muted-foreground hover:text-red-500 transition-colors p-0.5"
																		onClick={(e) => {
																			e.stopPropagation();
																			handleDeleteNewsItem(item.id!, e);
																		}}
																		title={t("community:news.deleteNews")}
																	>
																		<Trash2 className="w-3 h-3" />
																	</button>
																</div>
															)}
														</div>
													</div>
													<p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2 pl-5">
														{item.text}
													</p>
													<div className="flex gap-3 pt-1 text-[10px] text-muted-foreground border-t border-border/5 pl-5">
														<button
															className={cn(
																"flex items-center gap-1 transition-colors",
																likedNews.includes(item.id!)
																	? "text-primary font-bold cursor-default"
																	: "hover:text-primary",
															)}
															onClick={(e) => {
																e.stopPropagation();
																handleNewsLike(item.id!, e);
															}}
														>
															<ThumbsUp
																className={cn(
																	"w-3 h-3",
																	likedNews.includes(item.id!) &&
																		"fill-primary/20",
																)}
															/>
															<span>{item.likes_count ?? 0}</span>
														</button>
														<div className="flex items-center gap-1">
															<MessageSquare className="w-3 h-3" />
															<span>{item.comments_count ?? 0}</span>
														</div>
													</div>
												</motion.div>
											))}

											{/* Regular News */}
											{regularNews
												.slice(
													(newsPage - 1) * NEWS_PER_PAGE,
													newsPage * NEWS_PER_PAGE,
												)
												.map((item, idx) => (
													<motion.div
														key={item.id}
														initial={{ opacity: 0, x: 10 }}
														animate={{ opacity: 1, x: 0 }}
														transition={{ delay: idx * 0.05 }}
														onClick={() => setSelectedNews(item)}
														className="p-3.5 rounded-lg border border-border/30 bg-card/20 hover:bg-card/45 transition-colors cursor-pointer space-y-1.5 group animate-fadeIn"
													>
														<div className="flex justify-between items-center gap-2">
															<h4 className="text-xs font-bold text-foreground/90 group-hover:text-primary transition-colors line-clamp-1 flex-1">
																{item.title}
															</h4>
															<div className="flex items-center gap-1.5 shrink-0">
																<span className="text-[8px] text-muted-foreground font-mono">
																	{item.date}
																</span>
																{adminKey && item.id !== undefined && (
																	<div className="flex items-center gap-1">
																		<button
																			className="text-muted-foreground hover:text-primary transition-colors p-0.5"
																			onClick={(e) => {
																				e.stopPropagation();
																				handleTogglePinNewsItem(item.id!, true, e);
																			}}
																			title={isRu ? "Закрепить" : "Pin"}
																		>
																			<Pin className="w-3 h-3" />
																		</button>
																		<button
																			className="text-muted-foreground hover:text-red-500 transition-colors p-0.5"
																			onClick={(e) => {
																				e.stopPropagation();
																				handleDeleteNewsItem(item.id!, e);
																			}}
																			title={t("community:news.deleteNews")}
																		>
																			<Trash2 className="w-3 h-3" />
																		</button>
																	</div>
																)}
															</div>
														</div>
														<p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2">
															{item.text}
														</p>
														<div className="flex gap-3 pt-1 text-[10px] text-muted-foreground border-t border-border/5">
															<button
																className={cn(
																	"flex items-center gap-1 transition-colors",
																	likedNews.includes(item.id!)
																		? "text-primary font-bold cursor-default"
																		: "hover:text-primary",
																)}
																onClick={(e) => {
																	e.stopPropagation();
																	handleNewsLike(item.id!, e);
																}}
															>
																<ThumbsUp
																	className={cn(
																		"w-3 h-3",
																		likedNews.includes(item.id!) &&
																			"fill-primary/20",
																	)}
																/>
																<span>{item.likes_count ?? 0}</span>
															</button>
															<div className="flex items-center gap-1">
																<MessageSquare className="w-3 h-3" />
																<span>{item.comments_count ?? 0}</span>
															</div>
														</div>
													</motion.div>
												))}
										</div>

										{/* News pagination */}
										{regularNews.length > NEWS_PER_PAGE && (
											<div className="flex justify-center items-center gap-3 mt-4">
												<Button
													variant="outline"
													size="icon"
													className="h-7 w-7"
													disabled={newsPage === 1}
													onClick={() =>
														setNewsPage((prev) => Math.max(prev - 1, 1))
													}
												>
													<ChevronLeft className="w-3.5 h-3.5" />
												</Button>
												<span className="text-[11px] text-muted-foreground font-mono">
													{newsPage} / {Math.ceil(regularNews.length / NEWS_PER_PAGE)}
												</span>
												<Button
													variant="outline"
													size="icon"
													className="h-7 w-7"
													disabled={
														newsPage ===
														Math.ceil(regularNews.length / NEWS_PER_PAGE)
													}
													onClick={() =>
														setNewsPage((prev) =>
															Math.min(
																prev + 1,
																Math.ceil(regularNews.length / NEWS_PER_PAGE),
															),
														)
													}
												>
													<ChevronRight className="w-3.5 h-3.5" />
												</Button>
											</div>
										)}
									</>
								);
							})()
						) : (
							<p className="text-xs text-muted-foreground">
								{t("community:news.noUpdates", "No news updates available.")}
							</p>
						)}
					</div>

					{/* Feedback Form */}
					<div className="space-y-4">
						<div className="flex items-center gap-2 pb-2 border-b border-border/40">
							<MessageSquare className="w-4.5 h-4.5 text-primary" />
							<h3 className="text-base font-bold">
								{t("community:feedback.title", "Send Feedback")}
							</h3>
						</div>

						<Card className="border border-border/30 bg-card/10 backdrop-blur-sm relative overflow-hidden">
							<div className="absolute top-0 left-0 w-full h-0.5 bg-gradient-to-r from-primary/30 to-primary/80" />
							<CardHeader className="p-4 pb-2">
								<CardDescription className="text-[11px] leading-relaxed">
									{t("community:feedback.description")}
								</CardDescription>
							</CardHeader>
							<CardContent className="p-4 pt-2">
								<form onSubmit={handleFeedbackSubmit} className="space-y-3">
									<div className="space-y-1">
										<label className="text-[10px] font-medium text-muted-foreground">
											{t("community:feedback.category")}
										</label>
										<Select value={category} onValueChange={setCategory}>
											<SelectTrigger className="h-8 text-xs bg-black/20">
												<SelectValue />
											</SelectTrigger>
											<SelectContent>
												<SelectItem value="bug">
													{t("community:feedback.categories.bug")}
												</SelectItem>
												<SelectItem value="idea">
													{t("community:feedback.categories.idea")}
												</SelectItem>
												<SelectItem value="say_hello">
													{t("community:feedback.categories.say_hello")}
												</SelectItem>
											</SelectContent>
										</Select>
									</div>

									<div className="space-y-1">
										<label className="text-[10px] font-medium text-muted-foreground">
											{t("community:feedback.message")}
										</label>
										<Textarea
											value={feedbackText}
											onChange={(e) => setFeedbackText(e.target.value)}
											placeholder={t("community:feedback.placeholder")}
											className="min-h-[80px] text-xs resize-none bg-black/20"
											required
										/>
									</div>

									<div className="space-y-1">
										<label className="text-[10px] font-medium text-muted-foreground">
											{t("community:feedback.email")}
										</label>
										<Input
											type="email"
											value={contactEmail}
											onChange={(e) => setContactEmail(e.target.value)}
											placeholder="your-email@example.com"
											className="h-8 text-xs bg-black/20"
										/>
									</div>

									<Button
										type="submit"
										className="w-full gap-1.5 text-xs h-8"
										disabled={submittingFeedback}
									>
										{submittingFeedback ? (
											t("community:feedback.sending")
										) : (
											<>
												<Send className="w-3 h-3" />
												{t("community:feedback.send")}
											</>
										)}
									</Button>
								</form>
							</CardContent>
						</Card>
					</div>

					{/* My Support Tickets List */}
					{localFeedbackTickets.length > 0 && (
						<div className="space-y-4 pt-2">
							<div className="flex items-center gap-2 pb-2 border-b border-border/40">
								<MessageSquare className="w-4.5 h-4.5 text-primary" />
								<h3 className="text-base font-bold">
									{t("community:feedback.myTickets", "My Support Tickets")}
								</h3>
							</div>

							<div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
								{localFeedbackTickets.map((ticket) => {
									const unreadCount = getHubTicketUnreadCount(ticket.id);
									return (
										<Card
											key={ticket.id}
											onClick={() => setSelectedHubTicket(ticket)}
											className="border border-border/20 bg-card/25 hover:bg-card/45 hover:border-primary/30 transition-all cursor-pointer p-3 group relative overflow-hidden"
										>
											<div className="flex items-center justify-between gap-2 mb-1.5">
												<div className="flex items-center gap-1.5">
													<Badge
														variant="outline"
														className="text-[9px] uppercase tracking-wider h-4 py-0"
													>
														{ticket.category === "bug"
															? t("community:feedback.badges.bug")
															: ticket.category === "idea"
																? t("community:feedback.badges.idea")
																: t("community:feedback.badges.question")}
													</Badge>
													{unreadCount > 0 && (
														<span className="flex h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
													)}
												</div>
												<span className="text-[9px] text-muted-foreground">
													{new Intl.DateTimeFormat(isRu ? "ru-RU" : "en-US", {
														month: "short",
														day: "numeric",
														hour: "2-digit",
														minute: "2-digit",
													}).format(new Date(ticket.createdAt))}
												</span>
											</div>
											<div className="flex items-center justify-between gap-2">
												<p className="text-xs text-muted-foreground truncate group-hover:text-foreground transition-colors flex-1">
													{ticket.text}
												</p>
												{unreadCount > 0 && (
													<Badge
														variant="destructive"
														className="rounded-full px-1.5 py-0 bg-red-500 text-white text-[9px] font-bold shrink-0 animate-pulse"
													>
														{unreadCount}
													</Badge>
												)}
											</div>
										</Card>
									);
								})}
							</div>
						</div>
					)}
				</div>
			</div>

			{/* Create Topic Dialog */}
			<Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
				<DialogContent className="sm:max-w-[450px] border border-border/40 bg-card">
					<form onSubmit={handleCreateTopic}>
						<DialogHeader>
							<DialogTitle>
								{t("community:createTopic.title", "Create Discussion Topic")}
							</DialogTitle>
							<DialogDescription>
								{t("community:createTopic.description")}
							</DialogDescription>
						</DialogHeader>

						<div className="space-y-4 py-4">
							<div className="space-y-2">
								<Label htmlFor="topic-title">
									{t("community:createTopic.topicTitle", "Title")}
								</Label>
								<Input
									id="topic-title"
									required
									value={newTopicTitle}
									onChange={(e) => setNewTopicTitle(e.target.value)}
									placeholder={t(
										"community:createTopic.topicTitlePlaceholder",
										"Topic title...",
									)}
								/>
							</div>
							<div className="space-y-2">
								<Label htmlFor="topic-desc">
									{t("community:createTopic.topicDesc", "Description")}
								</Label>
								<Textarea
									id="topic-desc"
									required
									value={newTopicDesc}
									onChange={(e) => setNewTopicDesc(e.target.value)}
									placeholder={t(
										"community:createTopic.topicDescPlaceholder",
										"Provide details for the discussion...",
									)}
									className="min-h-[120px] resize-none"
								/>
							</div>
						</div>

						<DialogFooter>
							<Button
								type="button"
								variant="outline"
								onClick={() => setIsCreateDialogOpen(false)}
								disabled={publishingTopic}
							>
								{t("community:detailedView.cancel", "Cancel")}
							</Button>
							<Button type="submit" disabled={publishingTopic}>
								{publishingTopic
									? t("community:createTopic.publishing", "Publishing...")
									: t("community:createTopic.publish", "Publish")}
							</Button>
						</DialogFooter>
					</form>
				</DialogContent>
			</Dialog>

			{/* Detailed View Dialog */}
			<Dialog
				open={!!selectedTopic}
				onOpenChange={(open) => !open && setSelectedTopic(null)}
			>
				<DialogContent className="max-w-[1000px] max-h-[85vh] overflow-y-auto border border-border/40 bg-card p-6">
					{selectedTopic && (
						<div className="space-y-6">
							{/* Header */}
							<div className="flex justify-between items-start gap-4">
								<div className="space-y-2">
									<div className="flex flex-wrap gap-2 items-center">
										<Badge
											variant="outline"
											className="text-[10px] uppercase font-mono px-2"
										>
											{selectedTopic.topic_type === "strategy"
												? selectedTopic.symbol || "Strategy"
												: "Discussion"}
										</Badge>
										<span className={cn("text-xs text-muted-foreground flex items-center gap-1", selectedTopic.is_admin && "text-purple-400 font-bold")}>
											<UserIcon className={cn("w-3.5 h-3.5", selectedTopic.is_admin && "text-purple-400")} />
											{selectedTopic.author_name}
											{selectedTopic.is_admin && (
												<Badge
													variant="outline"
													className="text-[8px] h-3.5 border-purple-500/30 text-purple-400 bg-purple-500/5 px-1 py-0 uppercase tracking-wide shrink-0"
												>
													{isRu ? "Админ" : "Admin"}
												</Badge>
											)}
										</span>
									</div>
									<h2 className="text-xl md:text-2xl font-bold leading-tight">
										{getTopicTitle(selectedTopic, t)}
									</h2>
								</div>

								<div className="flex items-center gap-2 shrink-0">
									<Button
										size="sm"
										variant={
											likedTopics.includes(selectedTopic.id)
												? "default"
												: "outline"
										}
										className={cn(
											"h-8 gap-1.5 text-xs",
											likedTopics.includes(selectedTopic.id) &&
												"bg-primary text-primary-foreground pointer-events-none",
										)}
										onClick={() => handleLike(selectedTopic.id)}
									>
										<ThumbsUp
											className={cn(
												"w-3.5 h-3.5",
												likedTopics.includes(selectedTopic.id) &&
													"fill-current",
											)}
										/>
										<span>{selectedTopic.likes_count}</span>
									</Button>
									<div className="h-8 flex items-center gap-1.5 px-3 rounded-md border border-border/10 bg-black/10 text-xs text-muted-foreground">
										<MessageSquare className="w-3.5 h-3.5" />
										<span>{selectedTopic.comments_count || 0}</span>
									</div>
									{isDeletionAuthorized(selectedTopic.id) && (
										<Button
											size="sm"
											variant="outline"
											className="h-8 gap-1.5 text-xs border-red-500/20 text-red-400 hover:text-red-500 hover:bg-red-500/10"
											onClick={() => handleDeleteTopic(selectedTopic.id)}
										>
											<Trash2 className="w-3.5 h-3.5" />
											<span>
												{t("community:detailedView.delete", "Delete")}
											</span>
										</Button>
									)}
								</div>
							</div>

							{/* Description */}
							<div className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap bg-black/10 p-4 rounded-xl border border-border/10">
								{selectedTopic.description}
							</div>

							{/* Strategy-specific visualization & metrics */}
							{selectedTopic.topic_type === "strategy" && (
								<div className="space-y-5">
									{/* KPIs Grid */}
									{selectedTopic.kpis && (
										<div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
											<div className="bg-black/20 p-3 rounded-lg border border-border/15 text-center">
												<div className="text-[10px] text-muted-foreground uppercase">
													{t("community:detailedView.netProfit", "Net Profit")}
												</div>
												<div
													className={`text-base font-bold ${selectedTopic.kpis.total_pnl >= 0 ? "text-green-500" : "text-red-500"}`}
												>
													{selectedTopic.kpis.total_pnl >= 0 ? "+" : "-"}$
													{Math.abs(selectedTopic.kpis.total_pnl).toFixed(2)}
												</div>
											</div>
											<div className="bg-black/20 p-3 rounded-lg border border-border/15 text-center">
												<div className="text-[10px] text-muted-foreground uppercase">
													{t("community:detailedView.winRate", "Win Rate")}
												</div>
												<div className="text-base font-bold text-foreground">
													{(selectedTopic.kpis.win_rate || 0).toFixed(1)}%
												</div>
											</div>
											<div className="bg-black/20 p-3 rounded-lg border border-border/15 text-center">
												<div className="text-[10px] text-muted-foreground uppercase">
													{t(
														"community:detailedView.max_drawdown",
														"Max Drawdown",
													)}
												</div>
												<div className="text-base font-bold text-foreground">
													{(selectedTopic.kpis.max_drawdown || 0).toFixed(2)}%
												</div>
											</div>
											<div className="bg-black/20 p-3 rounded-lg border border-border/15 text-center">
												<div className="text-[10px] text-muted-foreground uppercase">
													{t(
														"community:detailedView.totalTrades",
														"Total Trades",
													)}
												</div>
												<div className="text-base font-bold text-foreground">
													{selectedTopic.kpis.trades || 0}
												</div>
											</div>
											<div className="bg-black/20 p-3 rounded-lg border border-border/15 text-center">
												<div className="text-[10px] text-muted-foreground uppercase">
													Sharpe
												</div>
												<div className="text-base font-bold text-foreground">
													{(selectedTopic.kpis.sharpe_ratio || 0).toFixed(2)}
												</div>
											</div>
										</div>
									)}

									{/* Equity Curve Chart */}
									{selectedTopic.equity_curve &&
										selectedTopic.equity_curve.length > 0 && (
											<div className="bg-black/15 border border-border/10 p-4 rounded-xl">
												<h3 className="text-sm font-semibold mb-3">
													{t(
														"community:detailedView.equityCurve",
														"Equity Curve",
													)}
												</h3>
												<EquityCurveChart
													run={{
														status: "COMPLETED",
														equity_curve_json: selectedTopic.equity_curve,
													}}
												/>
											</div>
										)}

									{/* Strategy JSON Inspector */}
									{selectedTopic.strategy_json && (
										<div className="bg-black/15 border border-border/10 p-4 rounded-xl space-y-3">
											<div className="flex justify-between items-center">
												<h3 className="text-sm font-semibold">
													{t(
														"community:detailedView.configTitle",
														"Strategy Configuration",
													)}
												</h3>
												<Button
													size="sm"
													className="h-8 gap-2 text-xs"
													onClick={() =>
														handleImport(
															selectedTopic.title,
															selectedTopic.description,
															selectedTopic.strategy_json,
														)
													}
													disabled={saveConfig.isPending}
												>
													<Download className="w-3.5 h-3.5" />
													{t("community:detailedView.import", "Import")}
												</Button>
											</div>
											<div className="relative max-h-60 overflow-y-auto rounded-lg bg-black/40 border border-border/15 p-3 text-xs font-mono">
												<pre className="text-muted-foreground/80 whitespace-pre-wrap">
													{JSON.stringify(selectedTopic.strategy_json, null, 2)}
												</pre>
											</div>
										</div>
									)}
								</div>
							)}

							{/* Comments Section */}
							<div className="border-t border-border/40 pt-5 space-y-4">
								<h3 className="text-base font-semibold flex items-center gap-2">
									<MessageSquare className="w-4 h-4 text-primary" />
									{t("community:detailedView.comments", "Comments")} (
									{comments.length})
								</h3>

								{/* Comments List */}
								<div className="space-y-3 max-h-60 overflow-y-auto pr-1">
									{loadingComments ? (
										<div className="space-y-2">
											{[1, 2].map((i) => (
												<div
													key={i}
													className="h-10 animate-pulse bg-muted/40 rounded-lg"
												/>
											))}
										</div>
									) : comments.length > 0 ? (
										comments.map((comment) => (
											<div
												key={comment.id}
												className="p-3 rounded-lg bg-card border border-border/20 space-y-1"
											>
												<div className="flex justify-between text-xs">
													<span className={cn("font-semibold text-foreground/80 flex items-center gap-1", comment.is_admin && "text-purple-400 font-bold")}>
														{comment.author_name}
														{comment.is_admin && (
															<Badge
																variant="outline"
																className="text-[8px] h-3.5 border-purple-500/30 text-purple-400 bg-purple-500/5 px-1 py-0 uppercase tracking-wide shrink-0"
															>
																{isRu ? "Админ" : "Admin"}
															</Badge>
														)}
													</span>
													<span className="text-[10px] text-muted-foreground font-mono">
														{new Date(comment.created_at).toLocaleString(
															isRu ? "ru-RU" : "en-US",
														)}
													</span>
												</div>
												<p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
													{comment.text}
												</p>
											</div>
										))
									) : (
										<p className="text-xs text-muted-foreground italic py-2">
											{t("community:detailedView.noComments")}
										</p>
									)}
								</div>

								{/* Add Comment Form */}
								<form onSubmit={handleCommentSubmit} className="space-y-3 pt-2">
									<Textarea
										required
										value={newCommentText}
										onChange={(e) => setNewCommentText(e.target.value)}
										placeholder={t("community:detailedView.replyPlaceholder")}
										className="min-h-[60px] text-xs resize-none bg-black/25"
									/>
									<div className="flex justify-end">
										<Button
											type="submit"
											size="sm"
											className="h-8 text-xs gap-1.5"
											disabled={submittingComment}
										>
											<Send className="w-3.5 h-3.5" />
											{submittingComment
												? t("community:detailedView.posting")
												: t("community:detailedView.postComment")}
										</Button>
									</div>
								</form>
							</div>
						</div>
					)}
				</DialogContent>
			</Dialog>

			{/* News Detailed View Dialog */}
			<Dialog
				open={!!selectedNews}
				onOpenChange={(open) => !open && setSelectedNews(null)}
			>
				<DialogContent className="max-w-[600px] max-h-[85vh] overflow-y-auto border border-border/40 bg-card p-6">
					{selectedNews && (
						<div className="space-y-6">
							{/* Header */}
							<div className="flex justify-between items-start gap-4">
								<div className="space-y-2">
									<div className="flex items-center gap-2">
										<Badge
											variant="outline"
											className="text-[10px] uppercase font-mono px-2"
										>
											{"Platform"}
										</Badge>
										<span className="text-[10px] text-muted-foreground font-mono">
											{selectedNews.date}
										</span>
									</div>
									<h2 className="text-lg md:text-xl font-bold leading-tight">
										{selectedNews.title}
									</h2>
								</div>

								<div className="flex items-center gap-2 shrink-0">
									<Button
										size="sm"
										variant={
											likedNews.includes(selectedNews.id!)
												? "default"
												: "outline"
										}
										className={cn(
											"h-8 gap-1.5 text-xs",
											likedNews.includes(selectedNews.id!) &&
												"bg-primary text-primary-foreground pointer-events-none",
										)}
										onClick={() => handleNewsLike(selectedNews.id!)}
									>
										<ThumbsUp
											className={cn(
												"w-3.5 h-3.5",
												likedNews.includes(selectedNews.id!) && "fill-current",
											)}
										/>
										<span>{selectedNews.likes_count ?? 0}</span>
									</Button>
									<div className="h-8 flex items-center gap-1.5 px-3 rounded-md border border-border/10 bg-black/10 text-xs text-muted-foreground">
										<MessageSquare className="w-3.5 h-3.5" />
										<span>{selectedNews.comments_count ?? 0}</span>
									</div>
								</div>
							</div>

							{/* Text */}
							<div className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap bg-black/10 p-4 rounded-xl border border-border/10">
								{selectedNews.text}
							</div>

							{/* Comments Section */}
							<div className="border-t border-border/40 pt-5 space-y-4">
								<h3 className="text-sm font-semibold flex items-center gap-2">
									<MessageSquare className="w-3.5 h-3.5 text-primary" />
									{"Comments"} ({newsComments.length})
								</h3>

								{/* Comments List */}
								<div className="space-y-3 max-h-60 overflow-y-auto pr-1">
									{loadingNewsComments ? (
										<div className="space-y-2">
											{[1, 2].map((i) => (
												<div
													key={i}
													className="h-10 animate-pulse bg-muted/40 rounded-lg"
												/>
											))}
										</div>
									) : newsComments.length > 0 ? (
										newsComments.map((comment) => (
											<div
												key={comment.id}
												className="p-3 rounded-lg bg-card border border-border/20 space-y-1"
											>
												<div className="flex justify-between text-xs">
													<span className={cn("font-semibold text-foreground/80 flex items-center gap-1", (comment as any).is_admin && "text-purple-400 font-bold")}>
														{comment.author_name}
														{(comment as any).is_admin && (
															<Badge
																variant="outline"
																className="text-[8px] h-3.5 border-purple-500/30 text-purple-400 bg-purple-500/5 px-1 py-0 uppercase tracking-wide shrink-0"
															>
																{isRu ? "Админ" : "Admin"}
															</Badge>
														)}
													</span>
													<span className="text-[10px] text-muted-foreground font-mono">
														{new Date(comment.created_at).toLocaleString(
															isRu ? "ru-RU" : "en-US",
														)}
													</span>
												</div>
												<p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
													{comment.text}
												</p>
											</div>
										))
									) : (
										<p className="text-xs text-muted-foreground italic py-2">
											{"No comments yet."}
										</p>
									)}
								</div>

								{/* Add Comment Form */}
								<form
									onSubmit={handleNewsCommentSubmit}
									className="space-y-3 pt-2"
								>
									<Textarea
										required
										value={newNewsCommentText}
										onChange={(e) => setNewNewsCommentText(e.target.value)}
										placeholder={
											"Write a reply..."
										}
										className="min-h-[60px] text-xs resize-none bg-black/25"
									/>
									<div className="flex justify-end">
										<Button
											type="submit"
											size="sm"
											className="h-8 text-xs gap-1.5"
											disabled={submittingNewsComment}
										>
											<Send className="w-3.5 h-3.5" />
											{submittingNewsComment
												? "Posting..."
												: "Post Comment"}
										</Button>
									</div>
								</form>
							</div>
						</div>
					)}
				</DialogContent>
			</Dialog>

			{/* Add News Item Dialog */}
			<Dialog open={isAddNewsOpen} onOpenChange={setIsAddNewsOpen}>
				<DialogContent className="sm:max-w-[450px] border border-border/40 bg-card">
					<form onSubmit={handleCreateNewsItem}>
						<DialogHeader>
							<DialogTitle>
								{t("community:addNews.title", "Add News Update")}
							</DialogTitle>
							<DialogDescription>
								{t("community:addNews.description")}
							</DialogDescription>
						</DialogHeader>

						<div className="space-y-4 py-4">
							<div className="space-y-2">
								<Label htmlFor="news-title">
									{t("community:addNews.newsTitle", "Title")}
								</Label>
								<Input
									id="news-title"
									required
									value={newsTitle}
									onChange={(e) => setNewsTitle(e.target.value)}
								/>
							</div>
							<div className="space-y-2">
								<Label htmlFor="news-text">
									{t("community:addNews.content", "Content")}
								</Label>
								<Textarea
									id="news-text"
									required
									value={newsText}
									onChange={(e) => setNewsText(e.target.value)}
									placeholder={t(
										"community:addNews.contentPlaceholder",
										"News item text...",
									)}
									className="min-h-[120px] resize-none"
								/>
							</div>
						</div>

						<DialogFooter>
							<Button
								type="button"
								variant="outline"
								onClick={() => setIsAddNewsOpen(false)}
								disabled={publishingNews}
							>
								{t("community:detailedView.cancel", "Cancel")}
							</Button>
							<Button type="submit" disabled={publishingNews}>
								{publishingNews
									? t("community:createTopic.publishing", "Publishing...")
									: t("community:addNews.publish", "Publish")}
							</Button>
						</DialogFooter>
					</form>
				</DialogContent>
			</Dialog>

			{/* Hub Ticket Chat Dialogue Modal */}
			<Dialog
				open={!!selectedHubTicket}
				onOpenChange={(open) => !open && setSelectedHubTicket(null)}
			>
				<DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto flex flex-col p-6 bg-background/95 backdrop-blur-md border border-border/85 rounded-2xl shadow-2xl">
					<DialogHeader className="pb-4 border-b border-border/40">
						<div className="flex items-center justify-between gap-4">
							<div className="flex items-center gap-2">
								<Badge
									variant="outline"
									className={`text-[10px] uppercase tracking-wider ${
										hubTicketStatus === "OPEN"
											? "bg-blue-500/10 text-blue-500 border-blue-500/20"
											: hubTicketStatus === "IN_PROGRESS"
												? "bg-amber-500/10 text-amber-500 border-amber-500/20"
												: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
									}`}
								>
									{hubTicketStatus}
								</Badge>
								<Badge variant="outline" className="capitalize text-[10px]">
									{selectedHubTicket?.category}
								</Badge>
							</div>
							{hubTicketStatus !== "CLOSED" &&
								hubTicketStatus !== "RESOLVED" && (
									<Button
										variant="outline"
										size="sm"
										className="h-7 text-[10px] gap-1 hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30"
										onClick={handleCloseHubTicket}
										disabled={updatingHubStatus}
									>
										{t("community:hubTicket.closeTicket", "Close Ticket")}
									</Button>
								)}
						</div>
						<DialogTitle className="text-lg font-bold tracking-tight mt-3">
							{t("community:hubTicket.details", "Feedback Ticket Details")}
						</DialogTitle>
						<DialogDescription className="text-xs text-muted-foreground">
							ID:{" "}
							<code className="font-mono text-[10px]">
								{selectedHubTicket?.id}
							</code>
						</DialogDescription>
					</DialogHeader>

					<div className="flex-1 py-4 space-y-6 overflow-y-auto max-h-[40vh] pr-1">
						{/* Initial text */}
						<div className="p-4 rounded-xl bg-muted/40 border border-border/30">
							<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">
								{t("community:hubTicket.yourFeedback", "Your Feedback")}
							</h4>
							<p className="text-xs whitespace-pre-wrap leading-relaxed">
								{selectedHubTicket?.text}
							</p>
						</div>

						{/* Dialogue Messages */}
						<div className="pt-4 border-t border-border/40 space-y-4">
							<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
								<MessageSquare className="w-3.5 h-3.5 text-primary" />
								{t("community:hubTicket.messageHistory", "Message History")}
							</h4>

							<div className="space-y-3">
								{loadingHubMessages ? (
									<div className="space-y-2">
										{[1, 2].map((i) => (
											<div
												key={i}
												className="h-12 animate-pulse bg-muted/30 rounded-xl"
											/>
										))}
									</div>
								) : hubTicketMessages.length > 0 ? (
									hubTicketMessages.map((msg) => (
										<div
											key={msg.id}
											className={`flex flex-col max-w-[85%] ${
												msg.isAdmin
													? "mr-auto items-start"
													: "ml-auto items-end"
											}`}
										>
											<div
												className={`p-3 rounded-2xl text-xs leading-relaxed ${
													msg.isAdmin
														? "bg-secondary text-secondary-foreground rounded-tl-none border border-border/30"
														: "bg-primary text-primary-foreground rounded-tr-none"
												}`}
											>
												{msg.text && (
													<p className="whitespace-pre-wrap">{msg.text}</p>
												)}
												{msg.image && (
													<div className="mt-2 rounded-xl overflow-hidden border border-border/20 max-h-[180px] bg-black/10 flex justify-center">
														<img
															src={msg.image}
															alt="Attached"
															className="max-w-full h-auto object-contain cursor-zoom-in hover:scale-[1.01] transition-transform"
															onClick={() => window.open(msg.image, "_blank")}
														/>
													</div>
												)}
											</div>
											<div className="flex items-center gap-1.5 mt-1 px-1 text-[10px] text-muted-foreground font-medium">
												{msg.isAdmin ? (
													<span className="text-primary font-semibold">
														{t(
															"community:hubTicket.supportName",
															"DepthSight Support",
														)}
													</span>
												) : (
													<span>{t("community:hubTicket.you", "You")}</span>
												)}
												<span>•</span>
												<span>
													{new Date(msg.createdAt).toLocaleTimeString(
														isRu ? "ru-RU" : "en-US",
														{
															hour: "2-digit",
															minute: "2-digit",
														},
													)}
												</span>
											</div>
										</div>
									))
								) : (
									<div className="text-center py-6 text-xs text-muted-foreground bg-muted/20 border border-dashed rounded-xl">
										{t("community:hubTicket.noReplies")}
									</div>
								)}
							</div>
						</div>
					</div>

					{/* Chat Input */}
					{hubTicketStatus !== "CLOSED" && hubTicketStatus !== "RESOLVED" ? (
						<div className="pt-4 border-t border-border/40 space-y-2">
							{newHubImage && (
								<div className="relative w-16 h-16 rounded-xl overflow-hidden border border-border/30 bg-muted/40 group">
									<img
										src={newHubImage}
										alt="Preview"
										className="w-full h-full object-cover"
									/>
									<button
										type="button"
										onClick={() => setNewHubImage(null)}
										className="absolute top-1 right-1 p-1 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity"
									>
										<X className="w-2.5 h-2.5" />
									</button>
								</div>
							)}

							<form
								onSubmit={handleSendHubReply}
								className="flex gap-2 items-end"
							>
								<input
									type="file"
									ref={hubReplyFileRef}
									onChange={handleHubReplyFileChange}
									accept="image/*"
									className="hidden"
								/>
								<Button
									type="button"
									variant="ghost"
									size="icon"
									className="h-10 w-10 text-muted-foreground hover:text-foreground shrink-0 rounded-xl border border-border/30 bg-card/25"
									onClick={() => hubReplyFileRef.current?.click()}
								>
									<Paperclip className="w-5 h-5" />
								</Button>
								<Textarea
									value={newHubReply}
									onChange={(e) => setNewHubReply(e.target.value)}
									placeholder={t(
										"community:hubTicket.typeMessage",
										"Type message...",
									)}
									className="min-h-[44px] max-h-[120px] text-xs resize-none bg-black/20 focus-visible:ring-primary flex-1"
									required={!newHubImage}
									onKeyDown={(e) => {
										if (e.key === "Enter" && !e.shiftKey) {
											e.preventDefault();
											handleSendHubReply(e);
										}
									}}
								/>
								<Button
									type="submit"
									disabled={
										submittingHubReply || (!newHubReply.trim() && !newHubImage)
									}
									className="h-10 px-4 shrink-0"
								>
									{submittingHubReply ? (
										t("community:feedback.sending")
									) : (
										<Send className="w-4 h-4" />
									)}
								</Button>
							</form>
						</div>
					) : (
						<div className="pt-4 border-t border-border/40 text-center text-xs text-muted-foreground italic">
							{t("community:hubTicket.ticketClosed")}
						</div>
					)}
				</DialogContent>
			</Dialog>
		</div>
	);
};

export default CommunityHub;
