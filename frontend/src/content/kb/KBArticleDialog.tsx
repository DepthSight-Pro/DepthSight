// src/content/kb/KBArticleDialog.tsx

import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { KBArticle } from "./articles";

import { getArticleContent } from "./loader";

interface KBArticleDialogProps {
	article: KBArticle | null;
	isOpen: boolean;
	onClose: () => void;
}

export const KBArticleDialog: React.FC<KBArticleDialogProps> = ({
	article,
	isOpen,
	onClose,
}) => {
	const { i18n } = useTranslation();
	const [content, setContent] = useState<string>("");
	const [isLoading, setIsLoading] = useState(false);

	const loadContent = useCallback(async () => {
		if (!article) return;
		setIsLoading(true);
		try {
			const text = await getArticleContent(i18n.language, article.id);
			setContent(text);
		} catch (error) {
			console.error("Error loading KB article:", error);
			setContent("Error loading content.");
		} finally {
			setIsLoading(false);
		}
	}, [article, i18n.language]);

	useEffect(() => {
		if (article && isOpen) {
			loadContent();
		}
	}, [article, isOpen, loadContent]);

	return (
		<Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
			<DialogContent className="max-w-3xl max-h-[85vh] flex flex-col p-0 overflow-hidden">
				<DialogHeader className="p-6 border-b border-border/40">
					<div className="flex items-center gap-2 mb-1">
						{article?.tags.map((tag) => (
							<span
								key={tag}
								className="text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full bg-primary/10 text-primary"
							>
								{tag}
							</span>
						))}
					</div>
					<DialogTitle className="text-2xl">{article?.title}</DialogTitle>
					<DialogDescription>{article?.description}</DialogDescription>
				</DialogHeader>

				<ScrollArea className="flex-1 p-6">
					<div className="prose prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-strong:text-foreground">
						{isLoading ? (
							<div className="flex flex-col gap-4 animate-pulse">
								<div className="h-4 bg-muted rounded w-3/4" />
								<div className="h-4 bg-muted rounded w-full" />
								<div className="h-4 bg-muted rounded w-5/6" />
							</div>
						) : (
							<ReactMarkdown remarkPlugins={[remarkGfm]}>
								{content}
							</ReactMarkdown>
						)}
					</div>
				</ScrollArea>
			</DialogContent>
		</Dialog>
	);
};
