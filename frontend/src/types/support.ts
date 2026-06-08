// src/types/support.ts

export interface SupportTicketCreate {
	subject: string;
	category: string;
	description: string;
	context?: Record<string, unknown>;
	screenshot?: string; // Base64
}

export interface SupportTicket {
	id: string;
	subject: string;
	category: string;
	description: string;
	status: "OPEN" | "IN_PROGRESS" | "RESOLVED" | "CLOSED";
	createdAt: string;
	updatedAt: string;
	context?: Record<string, unknown>;
	screenshot?: string;
	messages?: SupportTicketMessage[];
}

export interface AdminSupportTicket extends SupportTicket {
	userEmail: string;
}

export interface SupportTicketUpdate {
	status?: string;
	category?: string;
}

export interface SupportTicketResponse {
	message: string;
}

export interface SupportTicketMessage {
	id: number;
	ticketId: string;
	senderName: string;
	text: string;
	image?: string;
	isAdmin: boolean;
	createdAt: string;
}

export interface SupportTicketMessageCreate {
	text: string;
	senderName?: string;
	image?: string;
}
