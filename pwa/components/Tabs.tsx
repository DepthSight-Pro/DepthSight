// pwa/components/Tabs.tsx

import type React from "react";

interface TabsProps {
	tabs: {
		label: string;
		content: React.ReactNode;
	}[];
	activeTab: number; // Accept the active tab from outside
	setActiveTab: (index: number) => void; // Accept a function to change the tab
}

const Tabs: React.FC<TabsProps> = ({ tabs, activeTab, setActiveTab }) => {
	return (
		<div>
			<div className="flex border-b border-[hsl(var(--border))]">
				{tabs.map((tab, index) => (
					<button
						key={index}
						className={`py-2 px-4 text-sm font-medium transition-colors w-1/2 ${
							activeTab === index
								? "border-b-2 border-[hsl(var(--primary))] text-[hsl(var(--primary))]"
								: "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
						}`}
						onClick={() => setActiveTab(index)}
					>
						{tab.label}
					</button>
				))}
			</div>

			{/* Container for swipe with animation */}
			<div className="relative overflow-x-hidden">
				<div
					className="flex transition-transform duration-300 ease-in-out"
					style={{ transform: `translateX(-${activeTab * 100}%)` }}
				>
					{tabs.map((tab, index) => (
						<div key={index} className="w-full flex-shrink-0 pt-4">
							{tab.content}
						</div>
					))}
				</div>
			</div>
		</div>
	);
};

export default Tabs;
