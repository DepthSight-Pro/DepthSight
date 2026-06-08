// src/components/positions/EditSlTpModal.tsx

import { Loader2 } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { Button } from "@/components/ui/button";
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
import type { PositionData } from "@/types/api";

interface EditSlTpModalProps {
	isOpen: boolean;
	onClose: () => void;
	position: PositionData | null;
	onSubmit: (data: {
		stop_loss?: number | null;
		take_profit?: number | null;
	}) => void;
	isLoading: boolean;
}

export const EditSlTpModal: React.FC<EditSlTpModalProps> = ({
	isOpen,
	onClose,
	position,
	onSubmit,
	isLoading,
}) => {
	const { t } = useTranslation(["positions", "common"]); // Initialize useTranslation
	const [sl, setSl] = useState<string>("");
	const [tp, setTp] = useState<string>("");
	const [prevPositionId, setPrevPositionId] = useState<string | null>(null);

	const currentId = position?.id || null;
	if (currentId !== prevPositionId) {
		setPrevPositionId(currentId);
		if (position) {
			setSl(position.stop_loss?.toString() || "");
			setTp(position.take_profit?.toString() || "");
		} else {
			setSl("");
			setTp("");
		}
	}

	const handleSubmit = () => {
		const slValue = sl.trim() === "" ? null : parseFloat(sl);
		const tpValue = tp.trim() === "" ? null : parseFloat(tp);

		// Basic validation: ensure they are numbers if not null
		if (
			(sl.trim() !== "" && Number.isNaN(slValue!)) ||
			(tp.trim() !== "" && Number.isNaN(tpValue!))
		) {
			// Ideally, show an inline error message
			console.error("Invalid input for SL/TP"); // Use translated error
			// TODO: Consider using toast for user-facing error
			return;
		}
		onSubmit({ stop_loss: slValue, take_profit: tpValue });
	};

	if (!position) return null;

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="sm:max-w-[425px]">
				<DialogHeader>
					<DialogTitle>
						{t("editSlTpModal.title", { symbol: position.symbol })}
					</DialogTitle>
					<DialogDescription>
						{t("editSlTpModal.description", {
							price: position.entry_price.toFixed(2),
						})}
					</DialogDescription>
				</DialogHeader>
				<div className="grid gap-4 py-4">
					<div className="grid grid-cols-4 items-center gap-4">
						<Label htmlFor="stop-loss" className="text-right">
							{t("editSlTpModal.slLabel")}
						</Label>
						<Input
							id="stop-loss"
							type="number"
							value={sl}
							onChange={(e) => setSl(e.target.value)}
							placeholder={t("editSlTpModal.slPlaceholder")}
							className="col-span-3"
						/>
					</div>
					<div className="grid grid-cols-4 items-center gap-4">
						<Label htmlFor="take-profit" className="text-right">
							{t("editSlTpModal.tpLabel")}
						</Label>
						<Input
							id="take-profit"
							type="number"
							value={tp}
							onChange={(e) => setTp(e.target.value)}
							placeholder={t("editSlTpModal.tpPlaceholder")}
							className="col-span-3"
						/>
					</div>
				</div>
				<DialogFooter>
					<Button variant="outline" onClick={onClose} disabled={isLoading}>
						{t("common:cancel")}
					</Button>
					<Button onClick={handleSubmit} disabled={isLoading}>
						{isLoading ? (
							<Loader2 className="mr-2 h-4 w-4 animate-spin" />
						) : null}
						{isLoading ? t("common:loading") : t("editSlTpModal.saveButton")}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};
