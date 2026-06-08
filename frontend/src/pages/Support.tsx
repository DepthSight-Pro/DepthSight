// src/pages/Support.tsx

import { AnimatePresence, motion } from "framer-motion";
import {
	Activity,
	AlertCircle,
	Book,
	ChevronRight,
	Clock,
	Cpu,
	CreditCard,
	FileJson,
	FileText,
	History,
	Image as ImageIcon,
	LifeBuoy,
	Mail,
	MessageSquare,
	Paperclip,
	Send,
	X,
	Zap,
} from "lucide-react";
import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
	Accordion,
	AccordionContent,
	AccordionItem,
	AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { type KBArticle, kbArticles } from "@/content/kb/articles";
import { KBArticleDialog } from "@/content/kb/KBArticleDialog";
import { KBSearch } from "@/content/kb/KBSearch";
import {
	useCreateSupportTicket,
	useSendTicketMessage,
	useTicketMessages,
	useUserTickets,
} from "@/lib/api";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import type { SupportTicket, SupportTicketMessage } from "@/types/support";

const SupportPage = () => {
	const { t, i18n } = useTranslation(["support", "common"]);
	const { data: tickets, isLoading: isLoadingTickets } = useUserTickets();
	const createTicket = useCreateSupportTicket();

	// Ticket dialogue state
	const [selectedTicketId, setSelectedTicketId] = React.useState<string | null>(
		null,
	);
	const [replyText, setReplyText] = React.useState("");
	const [replyImage, setReplyImage] = React.useState<string | null>(null);
	const replyFileRef = React.useRef<HTMLInputElement>(null);
	const [lastReadMap, setLastReadMap] = React.useState<Record<string, string>>(
		{},
	);

	React.useEffect(() => {
		const stored = localStorage.getItem("depthsight_user_last_read");
		if (stored) {
			try {
				setLastReadMap(JSON.parse(stored));
			} catch {
				void 0;
			}
		}
	}, []);

	const { data: messages } = useTicketMessages(selectedTicketId || "");
	const sendMessage = useSendTicketMessage();

	React.useEffect(() => {
		if (selectedTicketId) {
			setLastReadMap((prev) => {
				const updated = {
					...prev,
					[selectedTicketId]: new Date().toISOString(),
				};
				localStorage.setItem(
					"depthsight_user_last_read",
					JSON.stringify(updated),
				);
				return updated;
			});
		}
	}, [selectedTicketId]);

	const getUnreadCount = React.useCallback(
		(ticket: SupportTicket) => {
			if (!ticket.messages || ticket.messages.length === 0) return 0;
			const lastReadStr = lastReadMap[ticket.id];
			if (!lastReadStr) {
				return ticket.messages.filter(
					(msg: SupportTicketMessage) => msg.isAdmin,
				).length;
			}
			const lastReadTime = new Date(lastReadStr).getTime();
			return ticket.messages.filter(
				(msg: SupportTicketMessage) =>
					msg.isAdmin && new Date(msg.createdAt).getTime() > lastReadTime,
			).length;
		},
		[lastReadMap],
	);

	const totalUnreadCount = React.useMemo(() => {
		return tickets?.reduce((acc, t) => acc + getUnreadCount(t), 0) || 0;
	}, [tickets, getUnreadCount]);

	const handleReplyFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		const file = e.target.files?.[0];
		if (file) {
			if (file.size > 5 * 1024 * 1024) {
				toast.error("File too large (max 5MB)");
				return;
			}
			const reader = new FileReader();
			reader.onloadend = () => {
				setReplyImage(reader.result as string);
			};
			reader.readAsDataURL(file);
		}
	};

	const handleSendReply = async (e: React.FormEvent) => {
		e.preventDefault();
		if ((!replyText.trim() && !replyImage) || !selectedTicketId) return;

		sendMessage.mutate(
			{
				ticketId: selectedTicketId,
				payload: {
					text: replyText.trim(),
					image: replyImage || undefined,
				},
			},
			{
				onSuccess: () => {
					setReplyText("");
					setReplyImage(null);
				},
				onError: (err) => {
					toast.error("Failed to send reply", { description: err.message });
				},
			},
		);
	};

	// Get editor state for context
	const editorState = useStrategyEditorStore();
	const [screenshot, setScreenshot] = React.useState<string | null>(null);
	const [selectedKBArticle, setSelectedKBArticle] =
		React.useState<KBArticle | null>(null);
	const [isKBDialogOpen, setIsKBDialogOpen] = React.useState(false);

	const lang = i18n.language.startsWith("ru") ? "ru" : "en";
	const articlesByLang = kbArticles[lang];

	const handleOpenArticle = (article: KBArticle) => {
		setSelectedKBArticle(article);
		setIsKBDialogOpen(true);
	};

	const getCategoryIcon = (category: string) => {
		switch (category) {
			case "getting-started":
				return <Book className="w-5 h-5" />;
			case "features":
				return <Zap className="w-5 h-5" />;
			case "billing":
				return <CreditCard className="w-5 h-5" />;
			case "advanced":
				return <Cpu className="w-5 h-5" />;
			default:
				return <FileText className="w-5 h-5" />;
		}
	};

	const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		const file = e.target.files?.[0];
		if (file) {
			if (file.size > 5 * 1024 * 1024) {
				toast.error("File too large (max 5MB)");
				return;
			}
			const reader = new FileReader();
			reader.onloadend = () => {
				setScreenshot(reader.result as string);
			};
			reader.readAsDataURL(file);
		}
	};

	const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
		e.preventDefault();

		const formData = new FormData(e.currentTarget);
		const category = formData.get("category") as string;

		// Collecting context if it's a bug report and we are in the editor
		let context;
		if (category === "bug" && editorState.id) {
			context = {
				strategyId: editorState.id,
				strategyName: editorState.name,
				config: editorState.toJson(),
				appVersion: "1.2.0-beta", // Ideally, pull from config
				url: window.location.href,
				userAgent: navigator.userAgent,
			};
		}

		const payload = {
			subject: formData.get("subject") as string,
			category,
			description: formData.get("description") as string,
			context,
			screenshot: screenshot || undefined,
		};

		createTicket.mutate(payload, {
			onSuccess: () => {
				toast.success(t("form.success"));
				(e.target as HTMLFormElement).reset();
				setScreenshot(null);
			},
			onError: (error: Error) => {
				toast.error(t("form.error"), {
					description: error.message,
				});
			},
		});
	};

	const getStatusBadge = (status: string) => {
		switch (status) {
			case "OPEN":
				return (
					<Badge
						variant="outline"
						className="bg-blue-500/10 text-blue-500 border-blue-500/20"
					>
						Open
					</Badge>
				);
			case "IN_PROGRESS":
				return (
					<Badge
						variant="outline"
						className="bg-amber-500/10 text-amber-500 border-amber-500/20"
					>
						In Progress
					</Badge>
				);
			case "RESOLVED":
				return (
					<Badge
						variant="outline"
						className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
					>
						Resolved
					</Badge>
				);
			default:
				return <Badge variant="secondary">{status}</Badge>;
		}
	};

	const containerVariants = {
		hidden: { opacity: 0 },
		visible: {
			opacity: 1,
			transition: {
				staggerChildren: 0.1,
			},
		},
	};

	const itemVariants = {
		hidden: { y: 20, opacity: 0 },
		visible: {
			y: 0,
			opacity: 1,
		},
	};

	return (
		<div className="min-h-screen bg-background text-foreground pb-20">
			{/* Hero Section */}
			<section className="relative overflow-hidden pt-16 pb-24 px-4 border-b border-border/40">
				<div className="absolute inset-0 bg-gradient-to-b from-primary/5 to-transparent pointer-events-none" />
				<div className="max-w-5xl mx-auto text-center relative z-10">
					<motion.div
						initial={{ scale: 0.8, opacity: 0 }}
						animate={{ scale: 1, opacity: 1 }}
						transition={{ duration: 0.5 }}
						className="inline-flex items-center justify-center p-3 mb-6 rounded-2xl bg-primary/10 text-primary"
					>
						<LifeBuoy className="w-8 h-8" />
					</motion.div>
					<motion.h1
						initial={{ y: 20, opacity: 0 }}
						animate={{ y: 0, opacity: 1 }}
						className="text-4xl md:text-5xl font-bold tracking-tight mb-4"
					>
						{t("title")}
					</motion.h1>
					<motion.p
						initial={{ y: 20, opacity: 0 }}
						animate={{ y: 0, opacity: 1 }}
						transition={{ delay: 0.1 }}
						className="text-xl text-muted-foreground mb-10 max-w-2xl mx-auto"
					>
						{t("subtitle")}
					</motion.p>

					<motion.div
						initial={{ y: 20, opacity: 0 }}
						animate={{ y: 0, opacity: 1 }}
						transition={{ delay: 0.2 }}
					>
						<KBSearch />
					</motion.div>
				</div>
			</section>

			{/* Knowledge Base Categories */}
			<section className="max-w-6xl mx-auto px-4 -mt-12 relative z-20">
				<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
					{["getting-started", "features", "billing", "advanced"].map(
						(cat, idx) => (
							<motion.div
								key={cat}
								initial={{ y: 20, opacity: 0 }}
								animate={{ y: 0, opacity: 1 }}
								transition={{ delay: 0.3 + idx * 0.1 }}
							>
								<Card className="h-full border-primary/10 bg-card/80 backdrop-blur-xl hover:border-primary/30 transition-all group overflow-hidden">
									<div className="absolute top-0 left-0 w-1 h-full bg-primary/20 group-hover:bg-primary transition-colors" />
									<CardHeader className="pb-2">
										<div className="p-2 rounded-lg bg-primary/10 text-primary w-fit mb-2">
											{getCategoryIcon(cat)}
										</div>
										<CardTitle className="text-sm font-bold uppercase tracking-wider">
											{t(`kb.categories.${cat}`)}
										</CardTitle>
									</CardHeader>
									<CardContent>
										<ul className="space-y-2">
											{articlesByLang
												.filter((a) => a.category === cat)
												.slice(0, 3)
												.map((article) => (
													<li key={article.id}>
														<button
															onClick={() => handleOpenArticle(article)}
															className="text-xs text-muted-foreground hover:text-primary transition-colors flex items-center gap-1 group/item"
														>
															<ChevronRight className="w-3 h-3 opacity-0 group-hover/item:opacity-100 -ml-4 group-hover/item:ml-0 transition-all" />
															{article.title}
														</button>
													</li>
												))}
										</ul>
									</CardContent>
								</Card>
							</motion.div>
						),
					)}
				</div>
			</section>

			<div className="max-w-6xl mx-auto px-4 mt-24">
				<Tabs defaultValue="new" className="w-full">
					<div className="flex items-center justify-between mb-8">
						<TabsList className="bg-card/50 border border-border">
							<TabsTrigger value="new" className="gap-2">
								<Send className="w-4 h-4" />
								{t("form.title")}
							</TabsTrigger>
							<TabsTrigger value="history" className="gap-2">
								<History className="w-4 h-4" />
								{t("history.title")}
								{tickets && tickets.length > 0 && (
									<span className="ml-1 px-1.5 py-0.5 rounded-full bg-primary text-[10px] text-primary-foreground font-bold">
										{tickets.length}
									</span>
								)}
								{totalUnreadCount > 0 && (
									<span className="ml-1 px-1.5 py-0.5 rounded-full bg-red-500 text-[10px] text-white font-bold animate-pulse">
										{totalUnreadCount}
									</span>
								)}
							</TabsTrigger>
						</TabsList>
					</div>

					<TabsContent value="new">
						<div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
							{/* Support Form */}
							<motion.div
								initial={{ x: -30, opacity: 0 }}
								animate={{ x: 0, opacity: 1 }}
								className="lg:col-span-2"
							>
								<Card className="border-primary/10 bg-card/30 backdrop-blur-md shadow-xl overflow-hidden relative">
									<div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/50 to-primary" />
									<CardHeader>
										<CardTitle className="text-2xl flex items-center gap-2">
											<Send className="w-5 h-5 text-primary" />
											{t("form.title")}
										</CardTitle>
										<CardDescription>
											{t("form.description_label_desc")}
										</CardDescription>
									</CardHeader>
									<CardContent>
										<form onSubmit={handleSubmit} className="space-y-6">
											<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
												<div className="space-y-2">
													<label className="text-sm font-medium text-muted-foreground">
														{t("form.subject")}
													</label>
													<Input
														name="subject"
														placeholder={t("form.subject_placeholder")}
														required
													/>
												</div>
												<div className="space-y-2">
													<label className="text-sm font-medium text-muted-foreground">
														{t("form.category")}
													</label>
													<Select name="category" defaultValue="bug" required>
														<SelectTrigger>
															<SelectValue
																placeholder={t("form.category_placeholder")}
															/>
														</SelectTrigger>
														<SelectContent>
															<SelectItem value="bug">
																{t("form.category_bug")}
															</SelectItem>
															<SelectItem value="feature">
																{t("form.category_feature")}
															</SelectItem>
															<SelectItem value="billing">
																{t("form.category_billing")}
															</SelectItem>
															<SelectItem value="other">
																{t("form.category_other")}
															</SelectItem>
														</SelectContent>
													</Select>
												</div>
											</div>
											<div className="space-y-2">
												<label className="text-sm font-medium text-muted-foreground">
													{t("form.description")}
												</label>
												<Textarea
													name="description"
													placeholder={t("form.description_placeholder")}
													className="min-h-[150px] resize-none"
													required
												/>
											</div>

											<div className="space-y-2">
												<label className="text-sm font-medium text-muted-foreground flex items-center gap-2">
													<ImageIcon className="w-4 h-4" />
													{t("form.screenshot_label")}
												</label>
												<div className="flex items-center gap-4">
													<Input
														type="file"
														accept="image/*"
														onChange={handleFileChange}
														className="bg-card/50 border-dashed cursor-pointer"
													/>
													{screenshot && (
														<div className="relative group shrink-0">
															<img
																src={screenshot}
																alt="Preview"
																className="w-12 h-12 object-cover rounded-md border border-primary/20"
															/>
															<button
																type="button"
																onClick={() => setScreenshot(null)}
																className="absolute -top-2 -right-2 bg-destructive text-destructive-foreground rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
															>
																<X className="w-3 h-3" />
															</button>
														</div>
													)}
												</div>
												<p className="text-[10px] text-muted-foreground">
													{t("form.screenshot_help")}
												</p>
											</div>
											<Button
												type="submit"
												className="w-full md:w-auto px-8 h-12 text-lg font-semibold"
												disabled={createTicket.isPending}
											>
												{createTicket.isPending ? (
													<div className="flex items-center gap-2">
														<div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
														{t("form.loading")}
													</div>
												) : (
													t("form.submit")
												)}
											</Button>
										</form>
									</CardContent>
								</Card>
							</motion.div>

							{/* FAQ Section */}
							<motion.div
								initial={{ x: 30, opacity: 0 }}
								animate={{ x: 0, opacity: 1 }}
								className="space-y-8"
							>
								<div>
									<h3 className="text-xl font-bold mb-6 flex items-center gap-2">
										<ChevronRight className="w-5 h-5 text-primary" />
										{t("faq.title")}
									</h3>
									<Accordion
										type="single"
										collapsible
										className="w-full space-y-2"
									>
										<AccordionItem
											value="item-1"
											className="border rounded-lg px-4 bg-card/20"
										>
											<AccordionTrigger className="hover:no-underline text-left">
												{t("faq.q1")}
											</AccordionTrigger>
											<AccordionContent className="text-muted-foreground">
												{t("faq.a1")}
											</AccordionContent>
										</AccordionItem>
										<AccordionItem
											value="item-2"
											className="border rounded-lg px-4 bg-card/20"
										>
											<AccordionTrigger className="hover:no-underline text-left">
												{t("faq.q2")}
											</AccordionTrigger>
											<AccordionContent className="text-muted-foreground">
												{t("faq.a2")}
											</AccordionContent>
										</AccordionItem>
										<AccordionItem
											value="item-3"
											className="border rounded-lg px-4 bg-card/20"
										>
											<AccordionTrigger className="hover:no-underline text-left">
												{t("faq.q3")}
											</AccordionTrigger>
											<AccordionContent className="text-muted-foreground">
												{t("faq.a3")}
											</AccordionContent>
										</AccordionItem>
									</Accordion>
								</div>

								<div className="p-6 rounded-2xl bg-gradient-to-br from-primary/10 to-transparent border border-primary/20">
									<h4 className="font-bold mb-2">{t("ai_helper.title")}</h4>
									<p className="text-sm text-muted-foreground mb-4">
										{t("ai_helper.desc")}
									</p>
									<Button
										variant="outline"
										className="w-full group"
										onClick={() =>
											window.dispatchEvent(new CustomEvent("open-ai-chat"))
										}
									>
										{t("ai_helper.button")}
										<motion.span
											animate={{ x: [0, 5, 0] }}
											transition={{ repeat: Infinity, duration: 1.5 }}
										>
											<ChevronRight className="ml-2 w-4 h-4" />
										</motion.span>
									</Button>
								</div>
							</motion.div>
						</div>
					</TabsContent>

					<TabsContent value="history">
						<div className="grid grid-cols-1 gap-4">
							{isLoadingTickets ? (
								Array.from({ length: 3 }).map((_, i) => (
									<Card
										key={i}
										className="animate-pulse bg-card/20 border-border/40"
									>
										<div className="h-24" />
									</Card>
								))
							) : tickets && tickets.length > 0 ? (
								<AnimatePresence mode="popLayout">
									{tickets.map((ticket: SupportTicket, idx: number) => (
										<motion.div
											key={ticket.id}
											initial={{ opacity: 0, y: 10 }}
											animate={{ opacity: 1, y: 0 }}
											transition={{ delay: idx * 0.05 }}
										>
											<Card
												className="hover:border-primary/30 transition-all bg-card/30 backdrop-blur-sm group cursor-pointer"
												onClick={() => setSelectedTicketId(ticket.id)}
											>
												<CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
													<div className="space-y-1">
														<CardTitle className="text-lg flex items-center gap-2">
															{ticket.subject}
															{getStatusBadge(ticket.status)}
															{getUnreadCount(ticket) > 0 && (
																<Badge
																	variant="destructive"
																	className="rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-red-500 text-white animate-pulse"
																>
																	{getUnreadCount(ticket)}
																</Badge>
															)}
														</CardTitle>
														<CardDescription className="flex items-center gap-4 text-xs">
															<span className="flex items-center gap-1">
																<Clock className="w-3 h-3" />
																{new Intl.DateTimeFormat("ru-RU", {
																	dateStyle: "medium",
																	timeStyle: "short",
																}).format(new Date(ticket.createdAt))}
															</span>
															<span className="capitalize px-1.5 py-0.5 rounded bg-muted/50 border border-border/50">
																{ticket.category}
															</span>
														</CardDescription>
													</div>
													<Button
														variant="ghost"
														size="icon"
														className="opacity-0 group-hover:opacity-100 transition-opacity"
													>
														<ChevronRight className="w-5 h-5" />
													</Button>
												</CardHeader>
												<CardContent>
													<p className="text-sm text-muted-foreground line-clamp-2">
														{ticket.description}
													</p>
													{ticket.context && (
														<div className="mt-3 flex items-center gap-2 text-[10px] text-primary/60 font-mono">
															<AlertCircle className="w-3 h-3" />
															{t("history.attachedContext")}: STRATEGY #
															{ticket.context.strategyId?.slice(0, 8)}
														</div>
													)}
												</CardContent>
											</Card>
										</motion.div>
									))}
								</AnimatePresence>
							) : (
								<div className="text-center py-20 bg-card/10 rounded-3xl border-2 border-dashed border-border/40">
									<div className="inline-flex p-4 rounded-full bg-muted mb-4">
										<History className="w-8 h-8 text-muted-foreground" />
									</div>
									<h3 className="text-xl font-bold mb-2">
										{t("history.empty")}
									</h3>
									<p className="text-muted-foreground max-w-xs mx-auto">
										{t("history.emptyDesc")}
									</p>
								</div>
							)}
						</div>
					</TabsContent>
				</Tabs>

				{/* Quick Links Grid */}
				<motion.div
					variants={containerVariants}
					initial="hidden"
					whileInView="visible"
					viewport={{ once: true }}
					className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 my-20"
				>
					<QuickLinkCard
						variants={itemVariants}
						icon={<Book className="w-6 h-6" />}
						title={t("quickLinks.docs.title")}
						description={t("quickLinks.docs.description")}
						href="#"
					/>
					<QuickLinkCard
						variants={itemVariants}
						icon={<MessageSquare className="w-6 h-6" />}
						title={t("quickLinks.telegram.title")}
						description={t("quickLinks.telegram.description")}
						href={
							import.meta.env.VITE_TELEGRAM_URL || "https://t.me/depthsight"
						}
						external
					/>
					<QuickLinkCard
						variants={itemVariants}
						icon={<Mail className="w-6 h-6" />}
						title={t("quickLinks.email.title")}
						description={t("quickLinks.email.description")}
						href={`mailto:${import.meta.env.VITE_SUPPORT_EMAIL || "support@depthsight.pro"}`}
					/>
					<QuickLinkCard
						variants={itemVariants}
						icon={<Activity className="w-6 h-6" />}
						title={t("quickLinks.status.title")}
						description={t("quickLinks.status.description")}
						href="#"
						color="text-emerald-500"
					/>
				</motion.div>
			</div>

			<KBArticleDialog
				article={selectedKBArticle}
				isOpen={isKBDialogOpen}
				onClose={() => setIsKBDialogOpen(false)}
			/>

			{/* Support Ticket Chat Dialog */}
			{(() => {
				const isRu = lang === "ru";
				const activeTicket = tickets?.find((t) => t.id === selectedTicketId);
				if (!activeTicket) return null;

				return (
					<Dialog
						open={!!selectedTicketId}
						onOpenChange={(open) => !open && setSelectedTicketId(null)}
					>
						<DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto flex flex-col p-6 bg-background/95 backdrop-blur-md border border-border/85 rounded-2xl shadow-2xl">
							<DialogHeader className="pb-4 border-b border-border/40">
								<div className="flex items-center gap-2 mb-2">
									{getStatusBadge(activeTicket.status)}
									<Badge variant="outline" className="capitalize">
										{activeTicket.category}
									</Badge>
								</div>
								<DialogTitle className="text-xl font-bold tracking-tight">
									{activeTicket.subject}
								</DialogTitle>
								<DialogDescription className="text-xs text-muted-foreground">
									Created:{" "}
									{new Intl.DateTimeFormat(isRu ? "ru-RU" : "en-US", {
										dateStyle: "medium",
										timeStyle: "short",
									}).format(new Date(activeTicket.createdAt))}
								</DialogDescription>
							</DialogHeader>

							<div className="flex-1 py-4 space-y-6 overflow-y-auto max-h-[50vh] pr-1">
								{/* Original Description */}
								<div className="p-4 rounded-xl bg-muted/40 border border-border/30">
									<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">
										{"Issue Description"}
									</h4>
									<p className="text-sm whitespace-pre-wrap leading-relaxed">
										{activeTicket.description}
									</p>
								</div>

								{/* Attached Screenshot */}
								{activeTicket.screenshot && (
									<div className="space-y-2">
										<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
											<ImageIcon className="w-3.5 h-3.5" />
											{"Attached Screenshot"}
										</h4>
										<div className="rounded-xl overflow-hidden border border-border/40 bg-black/10 flex justify-center max-h-[300px]">
											<img
												src={activeTicket.screenshot}
												alt="Screenshot"
												className="max-w-full h-auto object-contain cursor-zoom-in hover:scale-[1.01] transition-transform"
												onClick={() =>
													window.open(activeTicket.screenshot, "_blank")
												}
											/>
										</div>
									</div>
								)}

								{/* Tech Context */}
								{activeTicket.context && (
									<div className="space-y-2">
										<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
											<FileJson className="w-3.5 h-3.5" />
											{"Technical Context"}
										</h4>
										<div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
											{(activeTicket.context as Record<string, unknown>)
												.strategyId && (
												<div className="p-3 bg-card/50 border border-border/30 rounded-xl">
													<span className="text-muted-foreground block mb-0.5">
														{"Strategy ID"}
													</span>
													<code className="font-mono text-primary/80">
														{
															(activeTicket.context as Record<string, unknown>)
																.strategyId as string
														}
													</code>
												</div>
											)}
											{(activeTicket.context as Record<string, unknown>)
												.appVersion && (
												<div className="p-3 bg-card/50 border border-border/30 rounded-xl">
													<span className="text-muted-foreground block mb-0.5">
														{"App Version"}
													</span>
													<code>
														{
															(activeTicket.context as Record<string, unknown>)
																.appVersion as string
														}
													</code>
												</div>
											)}
											{(activeTicket.context as Record<string, unknown>)
												.url && (
												<div className="p-3 bg-card/50 border border-border/30 rounded-xl md:col-span-2">
													<span className="text-muted-foreground block mb-0.5">
														URL
													</span>
													<code className="break-all">
														{
															(activeTicket.context as Record<string, unknown>)
																.url as string
														}
													</code>
												</div>
											)}
										</div>
									</div>
								)}

								{/* Chat Dialogue Message History */}
								<div className="pt-4 border-t border-border/40 space-y-4">
									<h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
										<MessageSquare className="w-3.5 h-3.5 text-primary" />
										{"Dialogue with Support"}
									</h4>

									<div className="space-y-3">
										{messages && messages.length > 0 ? (
											messages.map((msg) => (
												<div
													key={msg.id}
													className={`flex flex-col max-w-[85%] ${
														msg.isAdmin
															? "mr-auto items-start"
															: "ml-auto items-end"
													}`}
												>
													<div
														className={`p-3 rounded-2xl text-sm leading-relaxed ${
															msg.isAdmin
																? "bg-secondary text-secondary-foreground rounded-tl-none border border-border/30"
																: "bg-primary text-primary-foreground rounded-tr-none"
														}`}
													>
														{msg.text && (
															<p className="whitespace-pre-wrap">{msg.text}</p>
														)}
														{msg.image && (
															<div className="mt-2 rounded-xl overflow-hidden border border-border/20 max-h-[220px] bg-black/10 flex justify-center">
																<img
																	src={msg.image}
																	alt="Attached"
																	className="max-w-full h-auto object-contain cursor-zoom-in hover:scale-[1.01] transition-transform"
																	onClick={() =>
																		window.open(msg.image, "_blank")
																	}
																/>
															</div>
														)}
													</div>
													<div className="flex items-center gap-1.5 mt-1 px-1 text-[10px] text-muted-foreground font-medium">
														<span>{msg.senderName}</span>
														<span>•</span>
														<span>
															{new Intl.DateTimeFormat(
																isRu ? "ru-RU" : "en-US",
																{
																	timeStyle: "short",
																},
															).format(new Date(msg.createdAt))}
														</span>
													</div>
												</div>
											))
										) : (
											<div className="text-center py-6 text-xs text-muted-foreground bg-muted/20 border border-dashed rounded-xl">
												{"No messages yet. Send a message to start the conversation."}
											</div>
										)}
									</div>
								</div>
							</div>

							{/* Chat Input Box */}
							<div className="pt-4 border-t border-border/40 space-y-2">
								{replyImage && (
									<div className="relative w-20 h-20 rounded-xl overflow-hidden border border-border/30 bg-muted/40 group">
										<img
											src={replyImage}
											alt="Preview"
											className="w-full h-full object-cover"
										/>
										<button
											type="button"
											onClick={() => setReplyImage(null)}
											className="absolute top-1 right-1 p-1 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity"
										>
											<X className="w-3 h-3" />
										</button>
									</div>
								)}

								<form
									onSubmit={handleSendReply}
									className="flex gap-2 items-end"
								>
									<input
										type="file"
										ref={replyFileRef}
										onChange={handleReplyFileChange}
										accept="image/*"
										className="hidden"
									/>
									<Button
										type="button"
										variant="ghost"
										size="icon"
										className="h-10 w-10 text-muted-foreground hover:text-foreground shrink-0 rounded-xl border border-border/30 bg-card/25"
										onClick={() => replyFileRef.current?.click()}
									>
										<Paperclip className="w-5 h-5" />
									</Button>
									<Textarea
										value={replyText}
										onChange={(e) => setReplyText(e.target.value)}
										placeholder={
											"Type your reply..."
										}
										className="min-h-[44px] max-h-[120px] text-xs resize-none bg-black/20 focus-visible:ring-primary flex-1"
										required={!replyImage}
										onKeyDown={(e) => {
											if (e.key === "Enter" && !e.shiftKey) {
												e.preventDefault();
												handleSendReply(e);
											}
										}}
									/>
									<Button
										type="submit"
										disabled={
											sendMessage.isPending ||
											(!replyText.trim() && !replyImage)
										}
										className="h-10 px-4 shrink-0"
									>
										{sendMessage.isPending ? (
											"Sending..."
										) : (
											<Send className="w-4 h-4" />
										)}
									</Button>
								</form>
							</div>
						</DialogContent>
					</Dialog>
				);
			})()}
		</div>
	);
};

interface QuickLinkCardProps {
	icon: React.ReactNode;
	title: string;
	description: string;
	href: string;
	external?: boolean;
	color?: string;
	variants?: import("framer-motion").Variants;
}

const QuickLinkCard: React.FC<QuickLinkCardProps> = ({
	icon,
	title,
	description,
	href,
	external = false,
	color = "text-primary",
	variants,
}) => {
	return (
		<motion.div variants={variants}>
			<a
				href={href}
				target={external ? "_blank" : undefined}
				rel={external ? "noopener noreferrer" : undefined}
				className="block group h-full"
			>
				<Card className="h-full border-primary/5 hover:border-primary/20 bg-card/40 hover:bg-card/60 transition-all duration-300 hover:shadow-lg hover:-translate-y-1 overflow-hidden relative">
					<CardHeader className="pb-2">
						<div
							className={`mb-3 p-3 rounded-xl bg-background border border-border group-hover:border-primary/30 transition-colors w-fit ${color}`}
						>
							{icon}
						</div>
						<CardTitle className="text-lg group-hover:text-primary transition-colors">
							{title}
						</CardTitle>
					</CardHeader>
					<CardContent>
						<CardDescription className="text-sm line-clamp-2">
							{description}
						</CardDescription>
					</CardContent>
				</Card>
			</a>
		</motion.div>
	);
};

export default SupportPage;
