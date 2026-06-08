// src/components/admin/ImpersonationBanner.tsx

import { AlertTriangle } from "lucide-react";
import type React from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";

export const ImpersonationBanner: React.FC = () => {
	const { user, isImpersonating, stopImpersonating } = useAuth();

	if (!isImpersonating) {
		return null;
	}

	return (
		<div className="fixed bottom-0 left-0 right-0 bg-yellow-500 text-yellow-900 p-3 z-50 flex items-center justify-center shadow-lg">
			<AlertTriangle className="h-5 w-5 mr-3" />
			<span className="font-semibold mr-4">
				You are currently logged in as {user?.username}.
			</span>
			<Button
				variant="outline"
				className="bg-yellow-100 hover:bg-white text-yellow-900 border-yellow-800"
				onClick={stopImpersonating}
			>
				Return to Admin Account
			</Button>
		</div>
	);
};
