// pwa/components/editor/InitializationBlock.tsx

import type React from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../../constants";
import { useStrategyEditorStore } from "../../stores/strategyEditorStore";
import type { PartialExit } from "../../types/strategyEditor";
import { DynamicValueInput } from "./DynamicValueInput";

interface InitializationBlockProps {
	className?: string;
}

const InitializationBlock: React.FC<InitializationBlockProps> = ({
	className = "",
}) => {
	const { t } = useTranslation("pwa-common");
	const params = useStrategyEditorStore((s) => s.initialization.params);
	const setInitializationParam = useStrategyEditorStore(
		(s) => s.setInitializationParam,
	);
	const addPartialExit = useStrategyEditorStore((s) => s.addPartialExit);
	const updatePartialExit = useStrategyEditorStore((s) => s.updatePartialExit);
	const removePartialExit = useStrategyEditorStore((s) => s.removePartialExit);

	return (
		<div className={`p-4 space-y-4 ${className}`}>
			{/* Position direction */}
			<div>
				<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
					{t("editor.direction")}
				</label>
				<div className="grid grid-cols-2 gap-2">
					<button
						onClick={() => setInitializationParam("direction", "LONG")}
						className={`py-3 px-4 rounded-lg text-sm font-medium transition ${
							params.direction === "LONG"
								? "bg-green-600 text-white"
								: "bg-[hsl(var(--secondary))] text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]"
						}`}
					>
						LONG
					</button>
					<button
						onClick={() => setInitializationParam("direction", "SHORT")}
						className={`py-3 px-4 rounded-lg text-sm font-medium transition ${
							params.direction === "SHORT"
								? "bg-red-600 text-white"
								: "bg-[hsl(var(--secondary))] text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]"
						}`}
					>
						SHORT
					</button>
				</div>
			</div>

			{/* Position size */}
			<div>
				<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
					{t("editor.positionSize")}
				</label>
				<div className="flex gap-2">
					<select
						value={params.risk_type}
						onChange={(e) =>
							setInitializationParam("risk_type", e.target.value)
						}
						className="flex-1 p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-sm text-[hsl(var(--foreground))] outline-none"
					>
						<option value="percent_balance">
							{t("editor.percentBalance")}
						</option>
						<option value="fixed_usd">{t("editor.fixedUsd")}</option>
					</select>
					<input
						type="number"
						value={params.risk_value}
						onChange={(e) =>
							setInitializationParam(
								"risk_value",
								parseFloat(e.target.value) || 0,
							)
						}
						className="w-24 p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-sm text-[hsl(var(--foreground))] outline-none"
					/>
				</div>
			</div>

			{/* Order type */}
			<div>
				<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
					{t("editor.orderType")}
				</label>
				<select
					value={params.order_type || "MARKET"}
					onChange={(e) => setInitializationParam("order_type", e.target.value)}
					className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-sm text-[hsl(var(--foreground))] outline-none"
				>
					<option value="MARKET">{t("editor.market")}</option>
					<option value="LIMIT_RETEST">{t("editor.limitRetest")}</option>
				</select>
			</div>

			{/* Entry price (only for LIMIT_RETEST) */}
			{params.order_type === "LIMIT_RETEST" && (
				<div>
					<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
						{t("editor.entryPrice")}
					</label>
					<DynamicValueInput
						value={params.entry_price}
						onChange={(v) => setInitializationParam("entry_price", v)}
					/>
				</div>
			)}

			{/* Stop loss */}
			<div>
				<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
					{t("editor.stopLoss")}
				</label>
				<div className="flex gap-2 mb-2">
					<select
						value={params.sl_type}
						onChange={(e) => setInitializationParam("sl_type", e.target.value)}
						className="flex-1 p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-sm text-[hsl(var(--foreground))] outline-none"
					>
						<option value="atr_multiplier">{t("editor.atrMultiplier")}</option>
						<option value="percent_from_price">
							{t("editor.percentFromPrice")}
						</option>
					</select>
				</div>
				<DynamicValueInput
					value={params.sl_value}
					onChange={(v) => setInitializationParam("sl_value", v)}
				/>
			</div>

			{/* Take profit */}
			<div>
				<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
					{t("editor.takeProfit")}
				</label>
				<div className="flex gap-2 mb-2">
					<select
						value={params.tp_type}
						onChange={(e) => setInitializationParam("tp_type", e.target.value)}
						className="flex-1 p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-sm text-[hsl(var(--foreground))] outline-none"
					>
						<option value="rr_multiplier">{t("editor.rrMultiplier")}</option>
						<option value="percent_from_price">
							{t("editor.percentFromPrice")}
						</option>
					</select>
				</div>
				<DynamicValueInput
					value={params.tp_value}
					onChange={(v) => setInitializationParam("tp_value", v)}
				/>
			</div>

			{/* Partial exits */}
			<div className="pt-4 border-t border-[hsl(var(--border))]">
				<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block">
					{t("editor.partialExits")}
				</label>
				<div className="space-y-2">
					{params.partial_exits.map((exit: PartialExit) => (
						<div
							key={exit.id}
							className="p-3 rounded-lg bg-[hsl(var(--secondary))]/50 space-y-2"
						>
							<div className="flex items-center gap-2">
								<input
									type="number"
									placeholder="Size %"
									value={exit.size_pct}
									onChange={(e) =>
										updatePartialExit(
											exit.id,
											"size_pct",
											parseFloat(e.target.value) || 0,
										)
									}
									className="flex-1 p-2 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md text-sm text-[hsl(var(--foreground))] outline-none"
								/>
								<button
									onClick={() => removePartialExit(exit.id)}
									className="p-2 rounded-md text-red-500 hover:bg-[hsl(var(--accent))]"
								>
									<ICONS.Trash2 className="w-4 h-4" />
								</button>
							</div>
							<div className="text-xs text-[hsl(var(--muted-foreground))]">
								{t("editor.atTP")}
							</div>
							<div className="flex gap-2">
								<select
									value={exit.tp_type}
									onChange={(e) =>
										updatePartialExit(exit.id, "tp_type", e.target.value)
									}
									className="flex-1 p-2 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-md text-sm text-[hsl(var(--foreground))] outline-none"
								>
									<option value="rr_multiplier">
										{t("editor.rrMultiplier")}
									</option>
									<option value="percent_from_price">
										{t("editor.percentFromPrice")}
									</option>
								</select>
							</div>
							<DynamicValueInput
								value={exit.tp_value}
								onChange={(newValue) =>
									updatePartialExit(exit.id, "tp_value", newValue)
								}
							/>
						</div>
					))}
				</div>
				<button
					onClick={addPartialExit}
					className="mt-2 w-full py-2 rounded-lg border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 flex items-center justify-center gap-2"
				>
					<ICONS.Plus className="w-4 h-4" />
					{t("editor.addPartialExit")}
				</button>
			</div>
		</div>
	);
};

export default InitializationBlock;
