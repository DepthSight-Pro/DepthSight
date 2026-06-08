// src/components/auth/ProtectedRoute.tsx
import type React from "react";
import { Navigate, Outlet } from "react-router-dom";
import { AppLoader } from "@/components/shared/AppLoader";
import { useAuth } from "@/context/AuthContext";

export const ProtectedRoute: React.FC = () => {
	const { token, isLoading } = useAuth();

	if (isLoading) {
		return (
			<div className="flex h-screen w-screen items-center justify-center bg-background">
				<AppLoader size="xl" fullLogo text="Loading platform..." />
			</div>
		);
	}

	if (!token) {
		return <Navigate to="/login" replace />;
	}

	return <Outlet />;
};

export default ProtectedRoute;
