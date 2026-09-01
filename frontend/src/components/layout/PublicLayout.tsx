// src/components/layout/PublicLayout.tsx

import type React from "react";
import { Outlet } from "react-router-dom";
import { Footer } from "./Footer";

export const PublicLayout: React.FC = () => {
	return (
		<div className="flex min-h-screen w-full flex-col bg-background">
			<main className="flex-grow">
				<Outlet />
			</main>
			<Footer className="mt-auto py-6" />
		</div>
	);
};

