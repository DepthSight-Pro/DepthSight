// src/components/auth/AdminRoute.tsx
import type React from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

const AdminRoute: React.FC = () => {
	const { user, isLoading } = useAuth(); // Adding isLoading

	if (isLoading) {
		return null; // Show nothing during loading
	}

	if (user && user.role !== "admin") {
		return <Navigate to="/" replace />;
	}

	// If admin, or if user hasn't loaded yet (and isLoading=false),
	// then it means we are no longer in a loading state and are not authorized.
	// ProtectedRoute above will redirect us.
	// But if we reached here and we are an admin, then show the content.
	return <Outlet />;
};

export default AdminRoute;
