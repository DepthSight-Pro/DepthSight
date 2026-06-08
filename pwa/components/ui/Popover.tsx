// pwa/components/ui/Popover.tsx

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface PopoverProps {
	children: React.ReactNode;
}

interface PopoverTriggerProps {
	children: React.ReactNode;
	asChild?: boolean;
}

interface PopoverContentProps {
	children: React.ReactNode;
	className?: string;
}

const PopoverContext = React.createContext<
	| {
			isOpen: boolean;
			setIsOpen: (open: boolean) => void;
			triggerRef: React.RefObject<HTMLDivElement>;
			contentRef: React.RefObject<HTMLDivElement>;
	  }
	| undefined
>(undefined);

export const Popover: React.FC<PopoverProps> = ({ children }) => {
	const [isOpen, setIsOpen] = useState(false);
	const triggerRef = useRef<HTMLDivElement>(null);
	const contentRef = useRef<HTMLDivElement>(null);

	const handleClickOutside = React.useCallback((event: MouseEvent) => {
		if (
			triggerRef.current &&
			!triggerRef.current.contains(event.target as Node) &&
			contentRef.current &&
			!contentRef.current.contains(event.target as Node)
		) {
			setIsOpen(false);
		}
	}, []);

	useEffect(() => {
		document.addEventListener("mousedown", handleClickOutside);
		return () => {
			document.removeEventListener("mousedown", handleClickOutside);
		};
	}, [handleClickOutside]);

	return (
		<PopoverContext.Provider
			value={{ isOpen, setIsOpen, triggerRef, contentRef }}
		>
			{children}
		</PopoverContext.Provider>
	);
};

export const PopoverTrigger: React.FC<PopoverTriggerProps> = ({
	children,
	asChild,
}) => {
	const { t } = useTranslation("pwa-common");
	const context = React.useContext(PopoverContext);
	if (!context) {
		throw new Error(t("errors.popoverTrigger"));
	}
	const { isOpen, setIsOpen, triggerRef } = context;

	const child = asChild ? (
		(React.Children.only(children) as React.ReactElement)
	) : (
		<button>{children}</button>
	);

	return React.cloneElement(child, {
		ref: triggerRef,
		onClick: () => setIsOpen(!isOpen),
	});
};

export const PopoverContent = React.forwardRef<
	HTMLDivElement,
	PopoverContentProps
>(
	// Corrected forwardRef
	({ children, className }, ref) => {
		// Added ref to props
		const { t } = useTranslation("pwa-common");
		const context = React.useContext(PopoverContext);
		if (!context) {
			throw new Error(t("errors.popoverContent"));
		}
		const { isOpen, contentRef } = context;

		if (!isOpen) return null;

		return (
			<div
				ref={ref || contentRef} // Use passed ref or context ref
				className={`absolute z-50 bg-[hsl(var(--popover))] text-[hsl(var(--popover-foreground))] border border-[hsl(var(--border))] rounded-md shadow-lg p-4 ${className}`}
				style={{ top: context.triggerRef.current?.offsetHeight || 0, left: 0 }} // Basic positioning
			>
				{children}
			</div>
		);
	},
);
PopoverContent.displayName = "PopoverContent"; // Added display name
