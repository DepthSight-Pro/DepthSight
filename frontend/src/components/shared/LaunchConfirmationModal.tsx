// src/components/shared/LaunchConfirmationModal.tsx

import { FileText, Loader2, Rocket } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";

export interface LaunchConfirmationModalProps {
	isOpen: boolean;
	onClose: () => void;
	onConfirm: (mode: "live" | "paper") => void;
	strategyName?: string;
	isLoading?: boolean;
}

export const LaunchConfirmationModal: React.FC<
	LaunchConfirmationModalProps
> = ({ isOpen, onClose, onConfirm, strategyName, isLoading }) => {
	const { t } = useTranslation(["strategies", "common"]);

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>
						{t("launchConfirm.title", { name: strategyName })}
					</DialogTitle>
					<DialogDescription>
						{t("launchConfirm.description")}
					</DialogDescription>
				</DialogHeader>
				<div className="py-4 grid grid-cols-2 gap-4">
					{/* --- Adding icons and loading state for buttons --- */}
					<Button
						variant="destructive"
						onClick={() => onConfirm("live")}
						disabled={isLoading}
					>
						{isLoading ? (
							<Loader2 className="mr-2 h-4 w-4 animate-spin" />
						) : (
							<Rocket className="mr-2 h-4 w-4" />
						)}
						{t("launchConfirm.liveButton")}
					</Button>
					<Button
						variant="secondary"
						onClick={() => onConfirm("paper")}
						disabled={isLoading}
					>
						{isLoading ? (
							<Loader2 className="mr-2 h-4 w-4 animate-spin" />
						) : (
							<FileText className="mr-2 h-4 w-4" />
						)}
						{t("launchConfirm.paperButton")}
					</Button>
				</div>
				<DialogFooter>
					<Button variant="ghost" onClick={onClose} disabled={isLoading}>
						{t("common:cancel")}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};
