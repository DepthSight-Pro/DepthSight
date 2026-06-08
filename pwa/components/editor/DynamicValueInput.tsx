// pwa/components/editor/DynamicValueInput.tsx

import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../../constants";
import type { DynamicParam as DynamicParamType } from "../../types/strategyEditor";
export type DynamicParam = DynamicParamType;

import { DynamicInputPicker } from "./DynamicInputPicker";

import type { TFunction } from "i18next";

interface DynamicValueInputProps {
	value: DynamicParam;
	onChange: (value: DynamicParam) => void;
	disabled?: boolean;
}

const formatLinkedValue = (value: DynamicParam, t: TFunction): string => {
	if (typeof value !== "object" || !value.source)
		return t("dynamicInput.linked");

	switch (value.source) {
		case "block_result":
			return `🔗 ${t("dynamicInput.block")} [${value.block_id?.substring(0, 4)}].${value.key}`;
		case "candle":
			return `🔗 ${t("dynamicInput.candle")}.${value.key}[${value.shift ?? 0}]`;
		case "market_info":
			return `🔗 ${t("dynamicInput.market")}.${value.key}`;
		case "position_state":
			return `🔗 ${t("dynamicPicker.categories.position")}: ${value.key}`;
		default:
			return `🔗 ${value.source}`;
	}
};

export const DynamicValueInput: React.FC<DynamicValueInputProps> = ({
	value,
	onChange,
	disabled,
}) => {
	const { t } = useTranslation("pwa-common");
	const [isPickerVisible, setIsPickerVisible] = useState(false);
	const wrapperRef = useRef<HTMLDivElement>(null);
	const isLinked = typeof value === "object" && value !== null;

	useEffect(() => {
		const handleClickOutside = (event: MouseEvent) => {
			if (
				wrapperRef.current &&
				!wrapperRef.current.contains(event.target as Node)
			) {
				setIsPickerVisible(false);
			}
		};
		document.addEventListener("mousedown", handleClickOutside);
		return () => document.removeEventListener("mousedown", handleClickOutside);
	}, []);

	const handleUnlink = () => {
		onChange(0);
		setIsPickerVisible(false);
	};

	const handleLink = (source: string, key?: string, block_id?: string) => {
		onChange({ source, key, block_id, shift: 0 });
		setIsPickerVisible(false);
	};

	const placeholderText = useMemo(() => {
		return isLinked
			? formatLinkedValue(value, t)
			: t("dynamicInput.staticValue");
	}, [value, isLinked, t]);

	const handleButtonClick = () => {
		if (isLinked) {
			handleUnlink();
		} else {
			setIsPickerVisible((prev) => !prev);
		}
	};

	return (
		<div className="w-full" ref={wrapperRef}>
			<div className="relative flex items-center gap-1">
				<input
					type="number"
					value={isLinked ? "" : (value as number)}
					onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
						onChange(parseFloat(e.target.value) || 0)
					}
					disabled={disabled || isLinked}
					placeholder={placeholderText}
					readOnly={isLinked}
					className={`flex-grow w-full p-2 bg-[hsl(var(--secondary))] border rounded-md text-sm outline-none transition-all focus:ring-1 focus:ring-[hsl(var(--primary))] ${isLinked ? "text-[hsl(var(--primary))] cursor-default" : "text-[hsl(var(--foreground))]"} ${isPickerVisible ? "border-[hsl(var(--primary))]" : "border-[hsl(var(--border))]"}`}
				/>
				<button
					onClick={handleButtonClick}
					disabled={disabled}
					className="shrink-0 p-2 rounded-md hover:bg-[hsl(var(--accent))]"
					aria-label={isLinked ? "Unlink value" : "Link value"}
				>
					{isLinked ? (
						<ICONS.X className="h-4 w-4" />
					) : (
						<ICONS.Link2 className="h-4 w-4" />
					)}
				</button>
			</div>

			<DynamicInputPicker isVisible={isPickerVisible} onLink={handleLink} />
		</div>
	);
};
