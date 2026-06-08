// src/content/kb/KBSearch.tsx

import { ArrowRight, Book, FileText, Search } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
	CommandDialog,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
	CommandSeparator,
} from "@/components/ui/command";
import { type KBArticle, kbArticles } from "./articles";
import { KBArticleDialog } from "./KBArticleDialog";

export const KBSearch: React.FC = () => {
	const { t, i18n } = useTranslation(["support"]);
	const [open, setOpen] = useState(false);
	const [selectedArticle, setSelectedArticle] = useState<KBArticle | null>(
		null,
	);
	const [isArticleOpen, setIsArticleOpen] = useState(false);

	const lang = i18n.language.startsWith("ru") ? "ru" : "en";
	const articles = kbArticles[lang];

	const handleSelect = (article: KBArticle) => {
		setSelectedArticle(article);
		setOpen(false);
		setIsArticleOpen(true);
	};

	return (
		<>
			<div
				className="relative max-w-xl mx-auto cursor-pointer group"
				onClick={() => setOpen(true)}
			>
				<Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground w-5 h-5 group-hover:text-primary transition-colors" />
				<div className="flex items-center w-full h-14 pl-12 pr-4 bg-card/50 backdrop-blur-sm border border-primary/20 rounded-md shadow-lg text-muted-foreground group-hover:border-primary/50 transition-all">
					{t("searchPlaceholder")}
				</div>
				<div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-1 px-1.5 py-0.5 rounded border border-border bg-muted text-[10px] font-mono text-muted-foreground">
					<span className="text-xs">⌘</span>K
				</div>
			</div>

			<CommandDialog open={open} onOpenChange={setOpen}>
				<CommandInput placeholder={t("searchPlaceholder")} />
				<CommandList>
					<CommandEmpty>No results found.</CommandEmpty>
					<CommandGroup heading="Knowledge Base">
						{articles.map((article) => (
							<CommandItem
								key={article.id}
								onSelect={() => handleSelect(article)}
								className="flex items-center gap-3 py-3"
							>
								<div className="p-2 rounded-lg bg-primary/10 text-primary">
									<FileText className="w-4 h-4" />
								</div>
								<div className="flex flex-col gap-0.5">
									<span className="font-medium">{article.title}</span>
									<span className="text-xs text-muted-foreground line-clamp-1">
										{article.description}
									</span>
								</div>
								<ArrowRight className="ml-auto w-4 h-4 text-muted-foreground/50" />
							</CommandItem>
						))}
					</CommandGroup>
					<CommandSeparator />
					<CommandGroup heading="Quick Help">
						<CommandItem
							onSelect={() =>
								window.open(
									import.meta.env.VITE_TELEGRAM_URL ||
										"https://t.me/depthsight",
									"_blank",
								)
							}
						>
							<Book className="mr-2 h-4 w-4" />
							<span>Telegram Community</span>
						</CommandItem>
					</CommandGroup>
				</CommandList>
			</CommandDialog>

			<KBArticleDialog
				article={selectedArticle}
				isOpen={isArticleOpen}
				onClose={() => setIsArticleOpen(false)}
			/>
		</>
	);
};
