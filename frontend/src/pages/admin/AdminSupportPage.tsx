// src/pages/admin/AdminSupportPage.tsx

import { format } from "date-fns";
import {
	AlertCircle,
	CheckCircle2,
	Clock,
	Eye,
	FileJson,
	Image as ImageIcon,
	MessageSquare,
	Paperclip,
	Send,
	X,
} from "lucide-react";
import React, { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
	useAdminTickets,
	useAdminUpdateTicket,
	useSendTicketMessage,
	useTicketMessages,
} from "@/lib/api";
import type { AdminSupportTicket } from "@/types/support";

const AdminSupportPage: React.FC = () => {
	const [statusFilter, setStatusFilter] = useState<string>("all");
	const [selectedTicket, setSelectedTicket] =
		useState<AdminSupportTicket | null>(null);

	const [replyText, setReplyText] = useState("");
	const [replyImage, setReplyImage] = useState<string | null>(null);
	const replyFileRef = React.useRef<HTMLInputElement>(null);

	const { data: messages } = useTicketMessages(selectedTicket?.id || "");
	const sendMessage = useSendTicketMessage();

	const { data: tickets, isLoading } = useAdminTickets(
		statusFilter === "all" ? undefined : statusFilter,
	);

	const [lastReadMap, setLastReadMap] = useState<Record<string, string>>({});

	React.useEffect(() => {
		const stored = localStorage.getItem("depthsight_admin_last_read");
		if (stored) {
			try {
				setLastReadMap(JSON.parse(stored));
			} catch {
				void 0;
			}
		}
	}, []);

	React.useEffect(() => {
		if (selectedTicket && messages) {
			setLastReadMap((prev) => {
				const updated = {
					...prev,
					[selectedTicket.id]: new Date().toISOString(),
				};
				localStorage.setItem(
					"depthsight_admin_last_read",
					JSON.stringify(updated),
				);
				return updated;
			});
		}
	}, [selectedTicket, messages]);

	const getUnreadCount = (ticket: AdminSupportTicket) => {
		if (!ticket.messages || ticket.messages.length === 0) return 0;
		const lastReadStr = lastReadMap[ticket.id];
		if (!lastReadStr) {
			return ticket.messages.filter(
				(msg: Record<string, unknown>) => !msg.isAdmin,
			).length;
		}
		const lastReadTime = new Date(lastReadStr).getTime();
		return ticket.messages.filter(
			(msg: Record<string, unknown>) =>
				!msg.isAdmin &&
				new Date(msg.createdAt as string).getTime() > lastReadTime,
		).length;
	};

	const unreadTicketsCount =
		tickets?.filter((t) => getUnreadCount(t) > 0).length || 0;

	const updateTicket = useAdminUpdateTicket();

	const handleStatusChange = (ticketId: string, newStatus: string) => {
		updateTicket.mutate({ ticketId, payload: { status: newStatus } });
	};

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
		if ((!replyText.trim() && !replyImage) || !selectedTicket) return;

		sendMessage.mutate(
			{
				ticketId: selectedTicket.id,
				payload: {
					text: replyText.trim(),
					image: replyImage || undefined,
				},
			},
			{
				onSuccess: () => {
					setReplyText("");
					setReplyImage(null);
					setSelectedTicket((prev) =>
						prev ? { ...prev, status: "IN_PROGRESS" } : null,
					);
				},
			},
		);
	};

	const getStatusBadge = (status: string) => {
		switch (status) {
			case "OPEN":
				return <Badge variant="destructive">Open</Badge>;
			case "IN_PROGRESS":
				return (
					<Badge className="bg-blue-500 hover:bg-blue-600">In Progress</Badge>
				);
			case "RESOLVED":
				return (
					<Badge className="bg-green-500 hover:bg-green-600">Resolved</Badge>
				);
			case "CLOSED":
				return <Badge variant="secondary">Closed</Badge>;
			default:
				return <Badge variant="outline">{status}</Badge>;
		}
	};

	return (
		<div className="space-y-6">
			<div className="flex justify-between items-center">
				<div>
					<h1 className="text-3xl font-bold mb-2">Support Tickets</h1>
					<p className="text-muted-foreground">
						Manage user bug reports and support requests
					</p>
				</div>

				<div className="flex gap-4">
					<Select value={statusFilter} onValueChange={setStatusFilter}>
						<SelectTrigger className="w-[180px]">
							<SelectValue placeholder="Filter by status" />
						</SelectTrigger>
						<SelectContent>
							<SelectItem value="all">All Statuses</SelectItem>
							<SelectItem value="OPEN">Open</SelectItem>
							<SelectItem value="IN_PROGRESS">In Progress</SelectItem>
							<SelectItem value="RESOLVED">Resolved</SelectItem>
							<SelectItem value="CLOSED">Closed</SelectItem>
						</SelectContent>
					</Select>
				</div>
			</div>

			<div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center gap-2 text-muted-foreground mb-2">
							<AlertCircle className="w-4 h-4 text-red-500" />
							<span>Open Tickets</span>
						</div>
						<div className="text-2xl font-bold">
							{tickets?.filter((t) => t.status === "OPEN").length || 0}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center gap-2 text-muted-foreground mb-2">
							<Clock className="w-4 h-4 text-blue-500" />
							<span>In Progress</span>
						</div>
						<div className="text-2xl font-bold">
							{tickets?.filter((t) => t.status === "IN_PROGRESS").length || 0}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center gap-2 text-muted-foreground mb-2">
							<CheckCircle2 className="w-4 h-4 text-green-500" />
							<span>Resolved Today</span>
						</div>
						<div className="text-2xl font-bold">
							{tickets?.filter((t) => t.status === "RESOLVED").length || 0}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6">
						<div className="flex items-center gap-2 text-muted-foreground mb-2">
							<MessageSquare className="w-4 h-4 text-red-500" />
							<span>Unread Tickets</span>
						</div>
						<div className="text-2xl font-bold text-red-500">
							{unreadTicketsCount}
						</div>
					</CardContent>
				</Card>
			</div>

			<div className="rounded-md border">
				<Table>
					<TableHeader>
						<TableRow>
							<TableHead className="w-[150px]">Date</TableHead>
							<TableHead>User</TableHead>
							<TableHead>Subject</TableHead>
							<TableHead>Category</TableHead>
							<TableHead>Status</TableHead>
							<TableHead className="text-right">Actions</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{isLoading ? (
							[...Array(5)].map((_, i) => (
								<TableRow key={i}>
									<TableCell colSpan={6}>
										<Skeleton className="h-10 w-full" />
									</TableCell>
								</TableRow>
							))
						) : tickets?.length === 0 ? (
							<TableRow>
								<TableCell
									colSpan={6}
									className="text-center py-10 text-muted-foreground"
								>
									No tickets found
								</TableCell>
							</TableRow>
						) : (
							tickets?.map((ticket) => (
								<TableRow
									key={ticket.id}
									className="cursor-pointer hover:bg-muted/50"
									onClick={() => setSelectedTicket(ticket)}
								>
									<TableCell className="text-sm">
										{format(new Date(ticket.createdAt), "MMM d, HH:mm")}
									</TableCell>
									<TableCell>
										<div className="font-medium">{ticket.userEmail}</div>
									</TableCell>
									<TableCell>
										<div className="font-medium flex items-center gap-2">
											<span className="line-clamp-1 flex-1">
												{ticket.subject}
											</span>
											{getUnreadCount(ticket) > 0 && (
												<Badge
													variant="destructive"
													className="rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-red-500 text-white shrink-0 animate-pulse"
												>
													{getUnreadCount(ticket)}
												</Badge>
											)}
										</div>
									</TableCell>
									<TableCell>
										<Badge variant="outline">{ticket.category}</Badge>
									</TableCell>
									<TableCell onClick={(e) => e.stopPropagation()}>
										<Select
											defaultValue={ticket.status}
											onValueChange={(val) =>
												handleStatusChange(ticket.id, val)
											}
										>
											<SelectTrigger className="w-[140px] h-8">
												<SelectValue>
													{getStatusBadge(ticket.status)}
												</SelectValue>
											</SelectTrigger>
											<SelectContent>
												<SelectItem value="OPEN">Open</SelectItem>
												<SelectItem value="IN_PROGRESS">In Progress</SelectItem>
												<SelectItem value="RESOLVED">Resolved</SelectItem>
												<SelectItem value="CLOSED">Closed</SelectItem>
											</SelectContent>
										</Select>
									</TableCell>
									<TableCell className="text-right">
										<Button variant="ghost" size="icon">
											<Eye className="w-4 h-4" />
										</Button>
									</TableCell>
								</TableRow>
							))
						)}
					</TableBody>
				</Table>
			</div>

			{/* Ticket Details Dialog */}
			<Dialog
				open={!!selectedTicket}
				onOpenChange={(open) => !open && setSelectedTicket(null)}
			>
				<DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
					<DialogHeader>
						<div className="flex items-center gap-2 mb-2">
							{selectedTicket && getStatusBadge(selectedTicket.status)}
							<Badge variant="outline">{selectedTicket?.category}</Badge>
						</div>
						<DialogTitle className="text-2xl">
							{selectedTicket?.subject}
						</DialogTitle>
						<div className="text-sm text-muted-foreground">
							From: {selectedTicket?.userEmail} •{" "}
							{selectedTicket &&
								format(new Date(selectedTicket.createdAt), "PPPP p")}
						</div>
					</DialogHeader>

					<div className="space-y-6 py-4">
						<Card className="bg-muted/30">
							<CardHeader className="py-3">
								<CardTitle className="text-sm font-medium">
									Description
								</CardTitle>
							</CardHeader>
							<CardContent>
								<p className="whitespace-pre-wrap">
									{selectedTicket?.description}
								</p>
							</CardContent>
						</Card>

						{selectedTicket?.screenshot && (
							<div className="space-y-3">
								<h4 className="text-sm font-semibold flex items-center gap-2">
									<ImageIcon className="w-4 h-4" />
									Attached Screenshot
								</h4>
								<div className="rounded-lg overflow-hidden border bg-black/5 flex justify-center">
									<img
										src={selectedTicket.screenshot}
										alt="User Screenshot"
										className="max-w-full h-auto cursor-zoom-in transition-transform hover:scale-[1.02]"
										onClick={() =>
											window.open(selectedTicket.screenshot, "_blank")
										}
									/>
								</div>
							</div>
						)}

						{(() => {
							const ticketContext = selectedTicket?.context as
								| {
										strategyId?: string;
										appVersion?: string;
										url?: string;
										config?: unknown;
								  }
								| undefined;
							if (!ticketContext) return null;
							return (
								<div className="space-y-3">
									<h4 className="text-sm font-semibold flex items-center gap-2">
										<FileJson className="w-4 h-4" />
										Technical Context
									</h4>
									<div className="grid grid-cols-2 gap-4 text-xs">
										<div className="p-3 bg-card border rounded-lg">
											<span className="text-muted-foreground block mb-1">
												Strategy ID
											</span>
											<code className="font-mono">
												{ticketContext.strategyId || "N/A"}
											</code>
										</div>
										<div className="p-3 bg-card border rounded-lg">
											<span className="text-muted-foreground block mb-1">
												App Version
											</span>
											<code>{ticketContext.appVersion || "N/A"}</code>
										</div>
										<div className="p-3 bg-card border rounded-lg col-span-2">
											<span className="text-muted-foreground block mb-1">
												URL
											</span>
											<code className="break-all">
												{ticketContext.url || "N/A"}
											</code>
										</div>
									</div>

									{!!ticketContext.config && (
										<Card>
											<CardHeader className="py-2 px-4 border-b">
												<CardTitle className="text-xs font-medium">
													Strategy Configuration (JSON)
												</CardTitle>
											</CardHeader>
											<CardContent className="p-0">
												<pre className="text-[10px] p-4 bg-black/90 text-green-400 overflow-x-auto max-h-[300px]">
													{JSON.stringify(ticketContext.config, null, 2)}
												</pre>
											</CardContent>
										</Card>
									)}
								</div>
							);
						})()}

						{/* Admin Ticket Chat Thread */}
						<div className="pt-6 border-t space-y-4">
							<h4 className="text-sm font-semibold flex items-center gap-2">
								<MessageSquare className="w-4 h-4 text-primary" />
								Message History & Reply Thread
							</h4>

							<div className="space-y-3 max-h-[300px] overflow-y-auto pr-1">
								{messages && messages.length > 0 ? (
									messages.map((msg) => (
										<div
											key={msg.id}
											className={`flex flex-col max-w-[85%] ${
												msg.isAdmin
													? "ml-auto items-end"
													: "mr-auto items-start"
											}`}
										>
											<div
												className={`p-3 rounded-2xl text-xs leading-relaxed ${
													msg.isAdmin
														? "bg-primary text-primary-foreground rounded-tr-none"
														: "bg-muted text-muted-foreground rounded-tl-none border border-border/30"
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
												<span>{msg.senderName}</span>
												<span>•</span>
												<span>
													{format(new Date(msg.createdAt), "HH:mm, MMM d")}
												</span>
											</div>
										</div>
									))
								) : (
									<div className="text-center py-6 text-xs text-muted-foreground bg-muted/20 border border-dashed rounded-xl">
										No dialogue history. Send a reply below to start the thread.
									</div>
								)}
							</div>

							<div className="space-y-2 pt-2">
								{replyImage && (
									<div className="relative w-16 h-16 rounded-xl overflow-hidden border border-border/30 bg-muted/40 group">
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
											<X className="w-2.5 h-2.5" />
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
										placeholder="Type a reply to the user..."
										className="min-h-[44px] max-h-[120px] text-xs resize-none bg-black/20 flex-1"
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
						</div>
					</div>
				</DialogContent>
			</Dialog>
		</div>
	);
};

export default AdminSupportPage;
