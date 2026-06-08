// pwa/components/BottomSheet.tsx

import type React from "react";
import { useTranslation } from "react-i18next";
import type { StrategyBlock } from "../types";

interface BottomSheetProps {
	isOpen: boolean;
	onClose: () => void;
	block: StrategyBlock | null;
}

const BottomSheet: React.FC<BottomSheetProps> = ({
	isOpen,
	onClose,
	block,
}) => {
	const { t } = useTranslation("pwa-common");
	if (!block) return null;

	const paramEntries = Object.entries(block.params);

	return (
		<>
			<div
				className={`fixed inset-0 bg-black/50 z-30 transition-opacity duration-300 ${isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
				onClick={onClose}
				onKeyDown={(e) => {
					if (e.key === "Enter" || e.key === " ") {
						onClose();
					}
				}}
				role="button"
				tabIndex={0}
				aria-label={t("buttons.close")}
			></div>
			<div
				className={`fixed bottom-0 left-0 right-0 bg-[hsl(var(--card))] rounded-t-3xl shadow-[-4px_0_20px_rgba(0,0,0,0.1)] p-6 max-w-md mx-auto z-40 transition-transform duration-300 ease-out ${isOpen ? "translate-y-0" : "translate-y-full"}`}
			>
				<div className="w-12 h-1 bg-[hsl(var(--border))] rounded-full mx-auto mb-5"></div>
				<h2 className="text-xl font-medium mb-5 text-[hsl(var(--card-foreground))]">
					{t("bottomSheet.editBlock", { blockName: block.name })}
				</h2>

				{paramEntries.map(([key, value]) => (
					<div className="mb-4" key={key}>
						<label
							htmlFor={`param-${key}`}
							className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
						>
							{key}
						</label>
						<input
							id={`param-${key}`}
							type={typeof value === "number" ? "number" : "text"}
							className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
							defaultValue={value}
						/>
					</div>
				))}

				<div className="flex gap-3 mt-6">
					<button
						type="button"
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90"
						onClick={onClose}
					>
						{t("buttons.cancel")}
					</button>
					<button
						type="button"
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
						onClick={onClose}
					>
						{t("buttons.save")}
					</button>
				</div>
			</div>
		</>
	);
};

export default BottomSheet;
