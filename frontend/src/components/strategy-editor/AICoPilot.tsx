// frontend/src/components/strategy-editor/AICoPilot.tsx

import { Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface AICoPilotProps {
	onSubmit: (text: string) => void;
	isGenerating: boolean;
	className?: string;
}

export const AICoPilot: React.FC<AICoPilotProps> = ({
	onSubmit,
	isGenerating,
	className,
}) => {
	const { t } = useTranslation("strategy-editor");
	const [prompt, setPrompt] = useState("");

	const placeholderExamples = t("ai.placeholders", { returnObjects: true });
	const placeholder = Array.isArray(placeholderExamples)
		? placeholderExamples.join("\n")
		: "Describe your strategy here...";

	const handleSubmit = () => {
		if (prompt.trim() && !isGenerating) {
			onSubmit(prompt);
		}
	};

	return (
		<div
			className={cn(
				"relative overflow-hidden p-6 w-full rounded-2xl border border-white/10 glass shadow-2xl",
				className,
			)}
		>
			{/* Ambient top glow */}
			<div className="pointer-events-none absolute -top-20 left-1/2 -translate-x-1/2 w-80 h-36 bg-cyan/15 rounded-full blur-3xl" />

			<div className="text-center mb-5 relative z-10">
				<div className="w-12 h-12 rounded-2xl bg-cyan/10 border border-cyan/30 flex items-center justify-center mx-auto mb-3 shadow-[0_0_20px_-4px_rgba(0,212,255,0.4)]">
					<Sparkles className="w-6 h-6 text-cyan animate-pulse" />
				</div>
				<h2 className="text-xl font-bold text-white tracking-wide">{t("ai.title")}</h2>
				<p className="text-xs text-white/60 mt-1 max-w-md mx-auto leading-relaxed">{t("ai.description")}</p>
			</div>

			<div className="relative z-10">
				<Textarea
					value={prompt}
					onChange={(e) => setPrompt(e.target.value)}
					placeholder={placeholder}
					className="min-h-[110px] p-3.5 pr-44 bg-white/[0.03] border-white/10 text-white placeholder:text-white/30 text-xs rounded-xl focus-visible:ring-cyan/30 leading-relaxed resize-y"
					disabled={isGenerating}
					onKeyDown={(e) => {
						if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
							handleSubmit();
						}
					}}
				/>
				<button
					type="button"
					onClick={handleSubmit}
					disabled={isGenerating || !prompt.trim()}
					className={cn(
						"group relative flex h-8 items-center gap-1.5 overflow-hidden rounded-lg px-3.5 text-xs font-semibold text-white transition-all absolute bottom-3 right-3",
						isGenerating || !prompt.trim()
							? "opacity-40 cursor-not-allowed bg-white/10 text-white/40"
							: "bg-gradient-to-r from-azure to-cyan shadow-[0_0_20px_-5px_rgba(0,212,255,0.85)] hover:shadow-[0_0_28px_-3px_rgba(0,212,255,1)] hover:brightness-110 cursor-pointer",
					)}
				>
					{!isGenerating && prompt.trim() && (
						<span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
					)}
					{isGenerating ? (
						<Loader2 className="w-3.5 h-3.5 mr-1 animate-spin text-white" />
					) : (
						<Sparkles size={13} className="animate-pulse mr-0.5" />
					)}
					<span>{t("ai.generateButton")}</span>
				</button>
			</div>

			<p className="text-[11px] font-mono text-white/40 mt-2.5 text-center">
				{t("ai.shortcutHint")}
			</p>
			<p className="text-[10px] text-white/30 mt-2 text-center leading-tight max-w-lg mx-auto">
				{t("ai.disclaimer")}
			</p>
		</div>
	);
};
