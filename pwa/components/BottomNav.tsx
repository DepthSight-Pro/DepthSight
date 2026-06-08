// pwa/components/BottomNav.tsx

import type React from "react";
import { useTranslation } from "react-i18next";
import { getNavItems } from "../constants";
import type { Screen } from "../types";

interface BottomNavProps {
	activeScreen: Screen;
	onNavigate: (screen: Screen) => void;
}

type NavItem = {
	id: Screen;
	label: string;
	icon: React.ElementType;
};

const BottomNav: React.FC<BottomNavProps> = ({ activeScreen, onNavigate }) => {
	const { t } = useTranslation("pwa-common");
	const NAV_ITEMS = getNavItems(t);
	return (
		<nav className="bg-[hsl(var(--background))] border-t border-[hsl(var(--border))] shadow-[0_-2px_10px_rgba(0,0,0,0.1)] flex justify-around py-2">
			{NAV_ITEMS.map((item: NavItem) => {
				const isActive = activeScreen === item.id;
				return (
					<button
						key={item.id}
						type="button"
						onClick={() => onNavigate(item.id)}
						className={`flex-1 bg-none border-none p-2 flex flex-col items-center gap-1 cursor-pointer transition-all duration-200 ${isActive ? "text-[hsl(var(--primary))]" : "text-[hsl(var(--muted-foreground))]"}`}
					>
						<item.icon className="w-6 h-6" />
						<span className="text-xs font-medium">{item.label}</span>
					</button>
				);
			})}
		</nav>
	);
};

export default BottomNav;
