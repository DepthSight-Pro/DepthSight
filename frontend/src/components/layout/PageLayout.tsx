import type React from "react";
import { useEffect } from "react";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { Footer } from "./Footer";

interface PageLayoutProps {
	title: string;
	description?: React.ReactNode;
	icon?: React.ElementType;
	children: React.ReactNode;
	headerActions?: React.ReactNode;
	hideHeader?: boolean;
}

export const PageLayout: React.FC<PageLayoutProps> = ({
	title,
	description,
	icon: Icon,
	children,
	headerActions,
	hideHeader = false,
}) => {
	useEffect(() => {
		document.title = `DepthSight - ${title}`;
	}, [title]);

	const { isMobile } = useSidebar();

	return (
		<div className="min-h-full flex flex-col justify-between overflow-x-hidden w-full min-w-0">
			<div className="p-4 sm:p-5 lg:p-6 flex-1 min-w-0 w-full">
				{isMobile && hideHeader && (
					<div className="mb-3 flex items-center">
						<SidebarTrigger className="h-8 w-8 text-white/70 hover:text-white border border-white/10 bg-white/5 hover:bg-white/10 rounded-lg shrink-0" />
					</div>
				)}
				{!hideHeader && (
					<header className="mb-6 flex items-start justify-between flex-shrink-0">
						<div className="flex items-center gap-3">
							{isMobile && (
								<SidebarTrigger className="h-8 w-8 text-white/70 hover:text-white border border-white/10 bg-white/5 hover:bg-white/10 rounded-lg shrink-0" />
							)}
							{Icon && <Icon className="w-7 h-7 text-primary" />}
							<div>
								<h1 className="text-2xl font-bold tracking-tight">{title}</h1>
								{description && (
									<div className="text-sm text-muted-foreground mt-1">
										{description}
									</div>
								)}
							</div>
						</div>
						<div className="flex items-center space-x-4">{headerActions}</div>
					</header>
				)}
				<div className="min-h-0 min-w-0 w-full">{children}</div>
			</div>
			<Footer className="mt-auto flex-shrink-0" />
		</div>
	);
};

