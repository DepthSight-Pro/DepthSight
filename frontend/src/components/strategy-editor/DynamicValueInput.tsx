// src/components/strategy-editor/DynamicValueInput.tsx

import { Link2, X } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { BlockLinkPopover } from "./BlockLinkPopover";

export type DynamicParam =
	| number
	| { source: string; key?: string; shift?: number; block_id?: string };

interface DynamicValueInputProps {
	value: DynamicParam;
	onChange: (value: DynamicParam) => void;
	disabled?: boolean;
	className?: string;
}

// --- Formatting function ---
const formatLinkedValue = (
	value: DynamicParam,
	t: (key: string) => string,
): string => {
	if (typeof value !== "object" || value === null || !value.source)
		return t("dynamicInput.linked");

	switch (value.source) {
		case "block_result":
			return `🔗 ${t("dynamicInput.block")} [${value.block_id?.substring(0, 4)}].${value.key}`;
		case "candle":
			return `🔗 ${t("dynamicInput.candle")}.${value.key}[${value.shift ?? 0}]`;
		case "position_state":
			return `🔗 ${t("dynamicInput.position")}.${value.key}`;
		default:
			return `🔗 ${value.source}`;
	}
};

export const DynamicValueInput: React.FC<DynamicValueInputProps> = ({
	value,
	onChange,
	disabled,
	className,
}) => {
	const { t } = useTranslation("strategy-editor");
	const isLinked = typeof value === "object" && value !== null;

	const handleUnlink = () => {
		onChange(0);
	};

	const handleLink = (source: string, key?: string, block_id?: string) => {
		onChange({ source, key, block_id });
	};

	// --- Use memoized placeholder ---
	const placeholderText = useMemo(() => {
		return isLinked
			? formatLinkedValue(value, t)
			: t("dynamicInput.staticValue");
	}, [value, isLinked, t]);

	return (
		<div
			className={cn(
				"strategy-dynamic-value-input flex items-center gap-1 w-full min-w-0",
				isLinked && "min-w-[18rem] sm:min-w-[24rem]",
				className,
			)}
			data-linked={isLinked ? "true" : "false"}
		>
			<Input
				type={isLinked ? "text" : "number"}
				value={isLinked ? placeholderText : (value as number)}
				onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
				readOnly={isLinked}
				disabled={disabled}
				placeholder={isLinked ? undefined : placeholderText}
				title={isLinked ? placeholderText : undefined}
				className={cn(
					"flex-grow min-w-0",
					isLinked && "font-mono text-xs text-foreground",
				)}
			/>
			{isLinked ? (
				<Button
					variant="ghost"
					size="icon"
					onClick={handleUnlink}
					disabled={disabled}
					className="shrink-0"
				>
					<X className="h-4 w-4" />
				</Button>
			) : (
				<Popover>
					<PopoverTrigger asChild>
						<Button
							variant="outline"
							size="icon"
							disabled={disabled}
							className="shrink-0"
						>
							<Link2 className="h-4 w-4" />
						</Button>
					</PopoverTrigger>
					<PopoverContent className="w-72 p-2">
						<BlockLinkPopover onLink={handleLink} />
					</PopoverContent>
				</Popover>
			)}
		</div>
	);
};
