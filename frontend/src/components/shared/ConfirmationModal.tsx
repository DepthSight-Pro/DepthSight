// src/components/shared/ConfirmationModal.tsx

import { AlertTriangle } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { AppLoader } from "./AppLoader";

interface ConfirmationModalProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	title: string;
	description: string;
	onConfirm: () => void;
	loading?: boolean;
}

export const ConfirmationModal: React.FC<ConfirmationModalProps> = ({
	open,
	onOpenChange,
	title,
	description,
	onConfirm,
	loading,
}) => {
	const { t } = useTranslation("common");

	return (
		<AlertDialog open={open} onOpenChange={onOpenChange}>
			<AlertDialogContent className="bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6 sm:max-w-[440px]">
				<AlertDialogHeader>
					<AlertDialogTitle className="flex items-center gap-2 text-white text-base font-semibold">
						<AlertTriangle className="text-rose-400 h-5 w-5" />
						{title}{" "}
						{/* Title is passed as a prop, assumed to be translated already or a key */}
					</AlertDialogTitle>
					<AlertDialogDescription className="text-xs text-white/50 leading-relaxed">
						{description}
					</AlertDialogDescription>{" "}
					{/* Description is passed as a prop */}
				</AlertDialogHeader>
				<AlertDialogFooter className="gap-2 pt-2 sm:gap-2">
					<AlertDialogCancel
						disabled={loading}
						className="rounded-xl border border-white/10 bg-white/[0.02] hover:bg-white/[0.06] text-white/60 hover:text-white text-xs h-9 px-4 mt-0"
					>
						{t("cancel")}
					</AlertDialogCancel>
					<AlertDialogAction
						onClick={onConfirm}
						disabled={loading}
						className="rounded-xl bg-rose-500 hover:bg-rose-600 text-white font-semibold text-xs h-9 px-4 shadow-[0_0_15px_-3px_rgba(244,63,94,0.6)]"
					>
						{loading ? <AppLoader size="sm" /> : t("confirmButton")}
					</AlertDialogAction>
				</AlertDialogFooter>
			</AlertDialogContent>
		</AlertDialog>
	);
};
