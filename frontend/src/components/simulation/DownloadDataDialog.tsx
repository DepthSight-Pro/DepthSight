// src/components/simulation/DownloadDataDialog.tsx

import { Download, Loader2 } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/hooks/use-toast";
import { useSimulationStore } from "./simulationStore";

const API_BASE = import.meta.env.VITE_PUBLIC_API_URL || "";

const readResponseError = async (response: Response) => {
	const data = await response.json().catch(() => null);
	return data?.detail || `Server error: ${response.statusText}`;
};

export const DownloadDataDialog: React.FC = () => {
	const { t } = useTranslation("simulation");
	const { toast } = useToast();
	const { token } = useAuth();
	const { availableAssets } = useSimulationStore();

	const [open, setOpen] = useState(false);
	const [isLoading, setIsLoading] = useState(false);

	// Form State
	const [symbols, setSymbols] = useState("");
	const [startDate, setStartDate] = useState("");
	const [endDate, setEndDate] = useState("");

	const handleAddExisting = () => {
		if (availableAssets.length === 0) return;
		const existingStr = availableAssets.join(", ");
		setSymbols((prev) => (prev ? `${prev}, ${existingStr}` : existingStr));
	};

	const handleDownload = async () => {
		if (!symbols || !startDate || !endDate) {
			toast({
				title: t("error", "Error"),
				description: t("fillAllFields", "Please fill all fields"),
				variant: "destructive",
			});
			return;
		}

		const symbolList = symbols
			.split(",")
			.map((s) => s.trim())
			.filter(Boolean);
		if (symbolList.length === 0) return;

		setIsLoading(true);
		try {
			const response = await fetch(`${API_BASE}/api/simulation/download_data`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					...(token ? { Authorization: `Bearer ${token}` } : {}),
				},
				body: JSON.stringify({
					symbols: symbolList,
					start_date: startDate,
					end_date: endDate,
				}),
			});

			if (!response.ok) {
				throw new Error(await readResponseError(response));
			}

			const data = await response.json();

			toast({
				title: t("success", "Success"),
				description:
					data.message || t("downloadComplete", "Download completed"),
			});
			setOpen(false);
		} catch (error) {
			console.error("Download error:", error);
			toast({
				title: t("error", "Error"),
				description:
					error instanceof Error
						? error.message
						: t("downloadFailed", "Download failed"),
				variant: "destructive",
			});
		} finally {
			setIsLoading(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={setOpen}>
			<DialogTrigger asChild>
				<Button variant="outline" size="sm" className="w-full">
					<Download className="w-4 h-4 mr-2" />
					{t("downloadData", "Download Data")}
				</Button>
			</DialogTrigger>
			<DialogContent className="sm:max-w-[425px]">
				<DialogHeader>
					<DialogTitle>
						{t(
							"downloadHistoricalData",
							"Download Historical Data (1m Klines)",
						)}
					</DialogTitle>
					<DialogDescription>
						{t(
							"downloadDescription",
							"Specify symbols and date range to download missing 1-minute klines (OHLCV) from Binance.",
						)}
					</DialogDescription>
				</DialogHeader>
				<div className="grid gap-4 py-4">
					<div className="grid gap-2">
						<div className="flex items-center justify-between">
							<Label htmlFor="symbols">
								{t("symbols", "Symbols (comma separated)")}
							</Label>
							<Button
								variant="link"
								size="sm"
								className="h-auto p-0 text-[10px] uppercase font-bold text-primary/70 hover:text-primary transition-colors"
								onClick={handleAddExisting}
							>
								+ {t("addExisting", "Add Existing Assets")} (
								{availableAssets.length})
							</Button>
						</div>
						<Textarea
							id="symbols"
							placeholder="BTCUSDT, ETHUSDT, SOLUSDT"
							value={symbols}
							onChange={(e) => setSymbols(e.target.value)}
							className="h-20 font-mono text-xs"
						/>
					</div>
					<div className="grid grid-cols-2 gap-4">
						<div className="grid gap-2">
							<Label htmlFor="start-date">{t("startDate", "Start Date")}</Label>
							<Input
								id="start-date"
								type="date"
								value={startDate}
								onChange={(e) => setStartDate(e.target.value)}
								className="col-span-3 text-xs"
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="end-date">{t("endDate", "End Date")}</Label>
							<Input
								id="end-date"
								type="date"
								value={endDate}
								onChange={(e) => setEndDate(e.target.value)}
								className="col-span-3 text-xs"
							/>
						</div>
					</div>
				</div>
				<DialogFooter>
					<Button type="submit" onClick={handleDownload} disabled={isLoading}>
						{isLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
						{isLoading
							? t("downloading", "Downloading...")
							: t("startDownload", "Start Download")}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};
