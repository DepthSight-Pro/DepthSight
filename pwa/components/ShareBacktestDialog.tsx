// pwa/components/ShareBacktestDialog.tsx

import type React from "react";
import { useState } from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { ICONS } from "../constants";
import { api } from "../services/api";

interface ShareBacktestDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	runId: string;
}

export const ShareBacktestDialog: React.FC<ShareBacktestDialogProps> = ({
	open,
	onOpenChange,
	runId,
}) => {
	const { t } = useTranslation("pwa-common");
	const [isStrategyNamePublic, setIsStrategyNamePublic] = useState(true);
	const [areParametersPublic, setAreParametersPublic] = useState(false);
	const [publishToLeaderboard, setPublishToLeaderboard] = useState(false);
	const [generatedUrl, setGeneratedUrl] = useState<string | null>(null);
	const [hasCopied, setHasCopied] = useState(false);
	const [isPending, setIsPending] = useState(false);

	const handleGenerateLink = async () => {
		setIsPending(true);
		try {
			const data = await api.shareBacktest({
				runId,
				isStrategyNamePublic,
				areParametersPublic,
				publishToLeaderboard,
			});
			setGeneratedUrl(data.shareUrl);
			toast.success(t("shareDialog.toast.successTitle"));
		} catch {
			toast.error(t("common.errorTitle"));
		} finally {
			setIsPending(false);
		}
	};

	const handleCopyToClipboard = () => {
		if (generatedUrl) {
			navigator.clipboard.writeText(generatedUrl);
			setHasCopied(true);
			toast.success(t("shareDialog.toast.copied"));
			setTimeout(() => setHasCopied(false), 2000);
		}
	};

	const handleClose = () => {
		onOpenChange(false);
		setTimeout(() => {
			setGeneratedUrl(null);
			setIsStrategyNamePublic(true);
			setAreParametersPublic(false);
		}, 300);
	};

	if (!open) return null;

	return (
		<div
			className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
			onClick={handleClose}
		>
			<div
				className="bg-[hsl(var(--background))] rounded-lg p-6 w-full max-w-sm"
				onClick={(e) => e.stopPropagation()}
			>
				<h3 className="text-lg font-medium">{t("shareDialog.title")}</h3>
				<p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">
					{t("shareDialog.description")}
				</p>

				{generatedUrl ? (
					<div className="space-y-4 py-4">
						<p className="text-sm text-[hsl(var(--muted-foreground))]">
							{t("shareDialog.successMessage")}
						</p>
						<div className="relative">
							<input
								value={generatedUrl}
								readOnly
								className="w-full p-2 border rounded-md bg-[hsl(var(--input))]"
							/>
							<button
								className="absolute top-1/2 right-1 -translate-y-1/2 p-2"
								onClick={handleCopyToClipboard}
							>
								{hasCopied ? (
									<ICONS.Check className="h-4 w-4 text-green-500" />
								) : (
									<ICONS.Copy className="h-4 w-4" />
								)}
							</button>
						</div>
					</div>
				) : (
					<div className="grid gap-6 py-4">
						<div className="flex items-center justify-between space-x-2">
							<label
								htmlFor="strategy-name-public"
								className="cursor-pointer text-sm"
							>
								{t("shareDialog.showStrategyName")}
							</label>
							<input
								type="checkbox"
								id="strategy-name-public"
								checked={isStrategyNamePublic}
								onChange={(e) => setIsStrategyNamePublic(e.target.checked)}
							/>
						</div>
						<div className="flex items-center justify-between space-x-2">
							<label
								htmlFor="parameters-public"
								className="cursor-pointer text-sm"
							>
								{t("shareDialog.showParameters")}
							</label>
							<input
								type="checkbox"
								id="parameters-public"
								checked={areParametersPublic}
								onChange={(e) => setAreParametersPublic(e.target.checked)}
							/>
						</div>
						<div className="flex items-center justify-between space-x-2">
							<label
								htmlFor="publish-leaderboard"
								className="cursor-pointer text-sm"
							>
								{t("shareDialog.publishToLeaderboard")}
							</label>
							<input
								type="checkbox"
								id="publish-leaderboard"
								checked={publishToLeaderboard}
								onChange={(e) => setPublishToLeaderboard(e.target.checked)}
							/>
						</div>
					</div>
				)}

				<div className="mt-4 flex justify-end">
					{generatedUrl ? (
						<button
							onClick={handleClose}
							className="px-4 py-2 bg-[hsl(var(--secondary))] rounded-md text-sm"
						>
							{t("buttons.close")}
						</button>
					) : (
						<button
							onClick={handleGenerateLink}
							disabled={isPending}
							className="px-4 py-2 bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] rounded-md text-sm"
						>
							{isPending && (
								<ICONS.Loader className="mr-2 h-4 w-4 animate-spin" />
							)}
							{t("shareDialog.generateLinkButton")}
						</button>
					)}
				</div>
			</div>
		</div>
	);
};
