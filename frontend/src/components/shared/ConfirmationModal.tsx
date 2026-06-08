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
			<AlertDialogContent>
				<AlertDialogHeader>
					<AlertDialogTitle className="flex items-center gap-2">
						<AlertTriangle className="text-destructive" />
						{title}{" "}
						{/* Title is passed as a prop, assumed to be translated already or a key */}
					</AlertDialogTitle>
					<AlertDialogDescription>{description}</AlertDialogDescription>{" "}
					{/* Description is passed as a prop */}
				</AlertDialogHeader>
				<AlertDialogFooter>
					<AlertDialogCancel disabled={loading}>
						{t("cancel")}
					</AlertDialogCancel>
					<AlertDialogAction
						onClick={onConfirm}
						disabled={loading}
						className="bg-destructive hover:bg-destructive/90"
					>
						{loading ? <AppLoader size="sm" /> : t("confirmButton")}
					</AlertDialogAction>
				</AlertDialogFooter>
			</AlertDialogContent>
		</AlertDialog>
	);
};
