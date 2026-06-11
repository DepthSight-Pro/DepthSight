// src/pages/admin/AdminLayout.tsx

import {
	Activity,
	ArrowLeft,
	ClipboardList,
	LayoutDashboard,
	Share2,
	Users,
	Database,
	ShieldAlert,
	LifeBuoy,
	HeartPulse,
} from "lucide-react";
import type React from "react";
import { Link, NavLink, Outlet } from "react-router-dom";

const AdminLayout: React.FC = () => {
	const navItems = [
		{
			to: "/admin",
			text: "Dashboard",
			icon: <LayoutDashboard className="h-4 w-4" />,
		},
		{ to: "/admin/users", text: "Users", icon: <Users className="h-4 w-4" /> },
		{
			to: "/admin/affiliates",
			text: "Affiliates",
			icon: <Share2 className="h-4 w-4" />,
		},
		{
			to: "/admin/analytics",
			text: "Analytics",
			icon: <ClipboardList className="h-4 w-4" />,
		},
		{
			to: "/admin/data-pipeline",
			text: "Data Pipeline",
			icon: <Database className="h-4 w-4" />,
		},
		{
			to: "/admin/error-logs",
			text: "Error Logs",
			icon: <ShieldAlert className="h-4 w-4" />,
		},
		{
			to: "/admin/support",
			text: "Support",
			icon: <LifeBuoy className="h-4 w-4 text-orange-500" />,
		},
		{
			to: "/admin/health",
			text: "Platform Health",
			icon: <HeartPulse className="h-4 w-4" />,
		},
	];

	return (
		<div className="flex flex-1 h-screen bg-background">
			<aside className="w-64 border-r bg-card p-4 flex flex-col">
				<h2 className="text-2xl font-bold mb-6">Admin Panel</h2>
				<nav className="flex flex-col space-y-2">
					{navItems.map((item) => (
						<NavLink
							key={item.to}
							to={item.to}
							end={item.to === "/admin"}
							className={({ isActive }) =>
								`flex items-center gap-3 rounded-lg px-3 py-2 transition-all hover:text-primary ${
									isActive ? "bg-muted text-primary" : "text-muted-foreground"
								}`
							}
						>
							{item.icon}
							{item.text}
						</NavLink>
					))}
				</nav>
				<div className="mt-auto">
					<Link
						to="/"
						className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground transition-all hover:text-primary"
					>
						<ArrowLeft className="h-4 w-4" />
						<span>Back to App</span>
					</Link>
				</div>
			</aside>
			<main className="flex-1 overflow-y-auto bg-muted/30">
				<div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6 lg:py-8">
					<Outlet />
				</div>
			</main>
		</div>
	);
};

export default AdminLayout;
