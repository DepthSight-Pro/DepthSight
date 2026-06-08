// src/components/PrivateRoute.tsx

import type React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { AppLoader } from "./shared/AppLoader";

const PrivateRoute: React.FC<{ children: React.ReactElement }> = ({
	children,
}) => {
	const { token, isLoading } = useAuth();
	const location = useLocation();

	if (isLoading) {
		return (
			<div className="flex h-screen w-screen items-center justify-center">
				<AppLoader size="lg" />
			</div>
		);
	}

	if (!token) {
		return <Navigate to="/login" state={{ from: location }} replace />;
	}

	return children;
};

export default PrivateRoute;
