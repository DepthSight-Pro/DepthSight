import { Check, Copy, Loader2 } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import { useBacktestRun, useShareBacktest } from "@/lib/api";

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
	const { t } = useTranslation(["research", "common"]);
	const { toast } = useToast();
	const { user } = useAuth();

	const [isStrategyNamePublic, setIsStrategyNamePublic] = useState(true);
	const [areParametersPublic, setAreParametersPublic] = useState(false);
	const [publishToLeaderboard, setPublishToLeaderboard] = useState(false);
	const [publishToHub, setPublishToHub] = useState(false);

	const [title, setTitle] = useState("");
	const [authorName, setAuthorName] = useState("");
	const [description, setDescription] = useState("");

	const [generatedUrl, setGeneratedUrl] = useState<string | null>(null);
	const [hasCopied, setHasCopied] = useState(false);

	const { data: backtestRun, isLoading: isBacktestLoading } =
		useBacktestRun(runId);
	const { mutate: shareBacktest, isPending } = useShareBacktest();

	useEffect(() => {
		if (backtestRun) {
			const params = backtestRun.parameters_json as Record<string, unknown>;
			const config = params?.config as Record<string, unknown>;
			const displayName =
				(params?.name as string) ||
				(params?.strategy_display_name as string) ||
				(config?.name as string) ||
				backtestRun.strategy_name ||
				"";
			setTitle(displayName);
		}
	}, [backtestRun]);

	useEffect(() => {
		if (user) {
			setAuthorName(user.username || "");
		}
	}, [user]);

	const handleGenerateLink = () => {
		const HUB_API_URL =
			import.meta.env.VITE_HUB_API_URL ||
			"https://app.depthsight.pro/api/v1/hub";

		shareBacktest(
			{
				runId,
				isStrategyNamePublic,
				areParametersPublic,
				publishToLeaderboard,
			},
			{
				onSuccess: async (data) => {
					setGeneratedUrl(data.shareUrl);

					if (publishToHub && backtestRun) {
						try {
							const hubPayload = {
								topic_type: "strategy",
								title: title || backtestRun.strategy_name || "Shared Strategy",
								description:
									description ||
									`Shared backtest result on ${backtestRun.symbol}`,
								author_name: authorName || user?.username || "Anonymous",
								symbol: backtestRun.symbol,
								period_start: backtestRun.start_date,
								period_end: backtestRun.end_date,
								kpis: backtestRun.kpi_results_json || null,
								equity_curve: backtestRun.equity_curve_json || null,
								strategy_json: areParametersPublic
									? backtestRun.parameters_json?.config ||
										backtestRun.parameters_json
									: null,
							};

							const response = await fetch(`${HUB_API_URL}/topics`, {
								method: "POST",
								headers: {
									"Content-Type": "application/json",
								},
								body: JSON.stringify(hubPayload),
							});

							if (!response.ok) {
								throw new Error("Failed to publish to Federation Hub.");
							}

							const responseData = await response.json();
							const deleteToken = responseData.delete_token;
							if (deleteToken) {
								const storedTokens = JSON.parse(
									localStorage.getItem("depthsight_hub_tokens") || "{}",
								);
								storedTokens[responseData.id] = deleteToken;
								localStorage.setItem(
									"depthsight_hub_tokens",
									JSON.stringify(storedTokens),
								);
							}

							toast({
								title: t("shareDialog.toast.successTitle"),
								description:
									"Backtest successfully published to Discovery Hub!",
							});
						} catch (error) {
							const err = error as Error;
							toast({
								variant: "destructive",
								title: "Hub Publication Failed",
								description:
									err.message || "Failed to publish to Federation Hub.",
							});
						}
					} else {
						toast({
							title: t("shareDialog.toast.successTitle"),
							description: t("shareDialog.toast.successDescription"),
						});
					}
				},
				onError: (error) => {
					toast({
						variant: "destructive",
						title: t("common:errorTitle"),
						description: error.message,
					});
				},
			},
		);
	};

	const handleCopyToClipboard = () => {
		if (generatedUrl) {
			navigator.clipboard.writeText(generatedUrl);
			setHasCopied(true);
			setTimeout(() => setHasCopied(false), 2000);
		}
	};

	const handleClose = () => {
		onOpenChange(false);
		// Reset state after dialog closes
		setTimeout(() => {
			setGeneratedUrl(null);
			setIsStrategyNamePublic(true);
			setAreParametersPublic(false);
			setPublishToLeaderboard(false);
			setPublishToHub(false);
			setDescription("");
		}, 300);
	};

	return (
		<Dialog open={open} onOpenChange={handleClose}>
			<DialogContent className="sm:max-w-[425px]">
				<DialogHeader>
					<DialogTitle>{t("shareDialog.title")}</DialogTitle>
					<DialogDescription>{t("shareDialog.description")}</DialogDescription>
				</DialogHeader>

				{generatedUrl ? (
					<div className="space-y-4 py-4">
						<p className="text-sm text-muted-foreground">
							{t("shareDialog.successMessage")}
						</p>
						<div className="relative">
							<Input value={generatedUrl} readOnly />
							<Button
								size="icon"
								variant="ghost"
								className="absolute top-1/2 right-1 -translate-y-1/2"
								onClick={handleCopyToClipboard}
							>
								{hasCopied ? (
									<Check className="h-4 w-4 text-green-500" />
								) : (
									<Copy className="h-4 w-4" />
								)}
							</Button>
						</div>
					</div>
				) : (
					<div className="grid gap-6 py-4">
						<div className="flex items-center justify-between space-x-2">
							<Label htmlFor="strategy-name-public" className="cursor-pointer">
								{t("shareDialog.showStrategyName")}
							</Label>
							<Switch
								id="strategy-name-public"
								checked={isStrategyNamePublic}
								onCheckedChange={setIsStrategyNamePublic}
							/>
						</div>
						<div className="flex items-center justify-between space-x-2">
							<Label htmlFor="parameters-public" className="cursor-pointer">
								{t("shareDialog.showParameters")}
							</Label>
							<Switch
								id="parameters-public"
								checked={areParametersPublic}
								onCheckedChange={setAreParametersPublic}
							/>
						</div>
						<div className="flex items-center justify-between space-x-2">
							<Label htmlFor="publish-leaderboard" className="cursor-pointer">
								{t("shareDialog.publishToLeaderboard")}
							</Label>
							<Switch
								id="publish-leaderboard"
								checked={publishToLeaderboard}
								onCheckedChange={setPublishToLeaderboard}
							/>
						</div>
						<div className="flex items-center justify-between space-x-2">
							<Label htmlFor="publish-hub" className="cursor-pointer">
								{t("shareDialog.publishToHub")}
							</Label>
							<Switch
								id="publish-hub"
								checked={publishToHub}
								onCheckedChange={setPublishToHub}
							/>
						</div>
						{publishToHub && (
							<div className="space-y-4 border-t pt-4 border-border mt-2">
								<div className="space-y-2">
									<Label htmlFor="hub-title">{t("shareDialog.title")}</Label>
									<Input
										id="hub-title"
										value={title}
										onChange={(e) => setTitle(e.target.value)}
										placeholder="e.g. My Awesome Strategy"
									/>
								</div>
								<div className="space-y-2">
									<Label htmlFor="hub-author">
										{t("shareDialog.authorName")}
									</Label>
									<Input
										id="hub-author"
										value={authorName}
										onChange={(e) => setAuthorName(e.target.value)}
										placeholder={t("shareDialog.authorNamePlaceholder")}
									/>
								</div>
								<div className="space-y-2">
									<Label htmlFor="hub-description">
										{t("shareDialog.hubDescription")}
									</Label>
									<Textarea
										id="hub-description"
										value={description}
										onChange={(e) => setDescription(e.target.value)}
										placeholder={t("shareDialog.descriptionPlaceholder")}
										className="min-h-[80px]"
									/>
								</div>
							</div>
						)}
					</div>
				)}

				<DialogFooter>
					{generatedUrl ? (
						<Button onClick={handleClose}>{t("common:actions.close")}</Button>
					) : (
						<Button
							onClick={handleGenerateLink}
							disabled={isPending || isBacktestLoading}
						>
							{isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
							{t("shareDialog.generateLinkButton")}
						</Button>
					)}
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};
