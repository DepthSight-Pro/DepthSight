// src/components/auth/AffiliateRoute.tsx
import type React from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

const AffiliateRoute: React.FC = () => {
	const { user, isLoading } = useAuth();

	if (isLoading) {
		return null;
	}

	if (!user || (user.role !== "affiliate" && user.role !== "admin")) {
		return <Navigate to="/" replace />;
	}

	return <Outlet />;
};

export default AffiliateRoute;
