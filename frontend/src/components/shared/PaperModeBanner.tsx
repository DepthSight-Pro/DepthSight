// src/components/shared/PaperModeBanner.tsx

import { AnimatePresence, motion } from "framer-motion";
import { ShieldAlert } from "lucide-react";
import type React from "react";
import { usePortfolioMode } from "@/context/PortfolioModeContext";

export const PaperModeBanner: React.FC = () => {
	const { mode } = usePortfolioMode();

	return (
		<AnimatePresence>
			{mode === "paper" && (
				<motion.div
					initial={{ y: 50, opacity: 0 }}
					animate={{ y: 0, opacity: 1 }}
					exit={{ y: 50, opacity: 0 }}
					transition={{ type: "spring", damping: 25, stiffness: 200 }}
					className="fixed bottom-0 left-0 right-0 z-[30] w-full"
				>
					<div className="bg-amber-500/90 backdrop-blur-md text-amber-950 py-2 px-4 shadow-[0_-4px_20px_rgba(0,0,0,0.2)] flex items-center justify-center border-t border-amber-600/30 overflow-hidden">
						{/* Animated background pulse effect */}
						<div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent animate-[shimmer_3s_infinite]" />

						<div className="relative flex items-center justify-center gap-3">
							<ShieldAlert className="h-4 w-4 text-amber-900 animate-pulse" />
							<span className="text-xs md:text-sm font-bold tracking-tight text-center">
								You are in Paper Trading mode. All trades are simulated.
							</span>
							<div className="hidden sm:flex items-center gap-2 px-2 py-0.5 bg-amber-900/10 rounded border border-amber-900/20 text-[10px] uppercase font-black opacity-80">
								Simulation Only
							</div>
						</div>
					</div>
				</motion.div>
			)}
		</AnimatePresence>
	);
};
