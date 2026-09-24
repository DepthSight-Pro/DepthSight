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
			<DialogContent className="max-w-4xl h-[85vh] flex flex-col p-0 overflow-hidden glass border border-white/10 rounded-2xl shadow-2xl backdrop-blur-2xl text-white">
				<DialogHeader className="p-8 border-b border-white/10 shrink-0">
					<div className="flex items-center gap-2 mb-2">
						{article?.tags.map((tag) => (
							<span
								key={tag}
								className="text-[10px] uppercase tracking-wider font-black px-2.5 py-1 rounded-full bg-primary/20 text-primary border border-primary/20"
							>
								{tag}
							</span>
						))}
					</div>
					<DialogTitle className="text-3xl font-black bg-gradient-to-br from-foreground to-foreground/70 bg-clip-text text-transparent tracking-tight">
						{article?.title}
					</DialogTitle>
					<DialogDescription className="text-base text-muted-foreground/80 mt-2">
						{article?.description}
					</DialogDescription>
				</DialogHeader>

				<ScrollArea className="flex-1 min-h-0">
					<div className="p-8">
						<div className="prose prose-invert max-w-none 
							prose-headings:text-foreground prose-headings:font-black prose-headings:tracking-tight
							prose-p:text-muted-foreground/90 prose-p:leading-relaxed prose-p:text-lg
							prose-strong:text-foreground prose-strong:font-bold
							prose-ul:list-disc prose-ol:list-decimal
							prose-li:text-muted-foreground/90
							prose-code:text-primary prose-code:bg-primary/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none
							prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border/50
							prose-img:rounded-xl prose-img:shadow-2xl
							prose-hr:border-border/40"
						>
							{isLoading ? (
								<div className="flex flex-col gap-6 animate-pulse">
									<div className="h-8 bg-muted rounded-lg w-3/4" />
									<div className="space-y-3">
										<div className="h-4 bg-muted rounded w-full" />
										<div className="h-4 bg-muted rounded w-full" />
										<div className="h-4 bg-muted rounded w-5/6" />
									</div>
									<div className="h-40 bg-muted rounded-xl w-full" />
								</div>
							) : (
								<ReactMarkdown remarkPlugins={[remarkGfm]}>
									{content}
								</ReactMarkdown>
							)}
						</div>
					</div>
				</ScrollArea>
			</DialogContent>
		</Dialog>
	);
};
