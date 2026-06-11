// src/App.tsx

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import {
	BrowserRouter,
	Route,
	Routes,
	useLocation,
	useNavigate,
	useParams,
} from "react-router-dom";
import ProtectedRoute from "@/components/auth/ProtectedRoute";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { PublicLayout } from "@/components/layout/PublicLayout";
import { SidebarProvider } from "@/components/ui/sidebar";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/context/AuthContext";
import { PortfolioModeProvider } from "@/context/PortfolioModeContext";
import { SymbolSelectionSettingsProvider } from "@/context/SymbolSelectionSettingsContext";
import { ThemeProvider } from "@/context/ThemeProvider";
import { WebSocketProvider } from "@/context/WebSocketProvider";
import AdminRoute from "./components/auth/AdminRoute";
import AffiliateRoute from "./components/auth/AffiliateRoute";
import { GeneDiscoveryNotification } from "./components/genome/GeneDiscoveryNotification";
import OnboardingTutorial from "./components/OnboardingTutorial";
import { PaperModeBanner } from "./components/shared/PaperModeBanner";
import HftDashboardPage from "./features/hft-dashboard/HftDashboardPage";
import AccountPage from "./pages/Account";
import AffiliateDashboard from "./pages/AffiliateDashboard";
import Analytics from "./pages/Analytics";
import AdminAffiliatesPage from "./pages/admin/AdminAffiliatesPage";
import AdminDashboardPage from "./pages/admin/AdminDashboardPage";
import AdminLayout from "./pages/admin/AdminLayout";
import AdminSupportPage from "./pages/admin/AdminSupportPage";
import AdminUserDetailPage from "./pages/admin/AdminUserDetailPage";
import AdminUsersPage from "./pages/admin/AdminUsersPage";
import AdminAnalyticsPage from "./pages/admin/AnalyticsPage";
import AdminAffiliateDetailPage from "./pages/admin/affiliates/AdminAffiliateDetailPage";
import ErrorLogsPage from "./pages/admin/ErrorLogsPage";
import PlatformHealthPage from "./pages/admin/PlatformHealthPage";
import DataPipelinePage from "./pages/admin/DataPipelinePage";
import BacktestViewerPage from "./pages/BacktestViewer";
import CommunityHub from "./pages/CommunityHub";
import ConfirmEmailPage from "./pages/ConfirmEmail";
import { FoundationVisualizerPage } from "./pages/diagnostics/FoundationVisualizerPage";
import EventLog from "./pages/EventLog";
import ForgotPasswordPage from "./pages/ForgotPassword";
import GeneticCommandCenter from "./pages/GeneticCommandCenter";
import Index from "./pages/Index";
import LaboratoryPage from "./pages/LaboratoryPage";
import LeaderboardPage from "./pages/LeaderboardPage";
// Page imports that EXIST in this application
import LoginPage from "./pages/Login";
import MLCorePage from "./pages/MLCorePage";
import NotFound from "./pages/NotFound";
import OptimizationViewerPage from "./pages/OptimizationViewerPage";
import PortfolioBacktestViewer from "./pages/PortfolioBacktestViewer";
import Positions from "./pages/Positions";
import RegisterPage from "./pages/Register";
import Research from "./pages/Research";
import ResetPasswordPage from "./pages/ResetPassword";
import Settings from "./pages/Settings";
import SharedReportPage from "./pages/SharedReportPage";
import Strategies from "./pages/Strategies";
import StrategyEditorPage from "./pages/StrategyEditor";
import SupportPage from "./pages/Support";

const queryClient = new QueryClient();

function ReferralTracker() {
	const { search } = useLocation();

	React.useEffect(() => {
		const params = new URLSearchParams(search);
		const ref = params.get("ref");
		if (ref) {
			localStorage.setItem("referralCode", ref);
		}
	}, [search]);

	return null;
}

function ReferralRedirect() {
	const { refCode } = useParams();
	const { search } = useLocation();
	const navigate = useNavigate();

	React.useEffect(() => {
		const params = new URLSearchParams(search);
		const queryRef = params.get("ref");
		// If refCode is 'register', it means the URL was /go/register?ref=REF...
		const effectiveRef =
			refCode === "register" && queryRef ? queryRef : refCode;

		if (effectiveRef && effectiveRef !== "register") {
			localStorage.setItem("referralCode", effectiveRef);
			// Notify the backend about the click (asynchronously)
			fetch(`/r/${effectiveRef}`).catch(() => {});
			// Navigating to the registration page
			navigate(`/register?ref=${effectiveRef}`, { replace: true });
		} else {
			navigate("/register", { replace: true });
		}
	}, [refCode, search, navigate]);

	return null;
}

function App() {
	return (
		<ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
			<SidebarProvider>
				<QueryClientProvider client={queryClient}>
					<BrowserRouter>
						<AuthProvider>
							<WebSocketProvider>
								<TooltipProvider>
									<ReferralTracker />
									<SymbolSelectionSettingsProvider>
										<PortfolioModeProvider>
											<Routes>
												<Route element={<PublicLayout />}>
													<Route path="/login" element={<LoginPage />} />
													<Route path="/register" element={<RegisterPage />} />
													<Route
														path="/r/:refCode"
														element={<ReferralRedirect />}
													/>
													<Route
														path="/confirm-email/:token"
														element={<ConfirmEmailPage />}
													/>
													<Route
														path="/forgot-password"
														element={<ForgotPasswordPage />}
													/>
													<Route
														path="/reset-password/:token"
														element={<ResetPasswordPage />}
													/>
													<Route
														path="/s/:publicSlug"
														element={<SharedReportPage />}
													/>
												</Route>

												{/* Routes for protected pages */}
												<Route element={<ProtectedRoute />}>
													<Route element={<AdminRoute />}>
														<Route path="/admin" element={<AdminLayout />}>
															<Route index element={<AdminDashboardPage />} />
															<Route
																path="users"
																element={<AdminUsersPage />}
															/>
															<Route
																path="users/:id"
																element={<AdminUserDetailPage />}
															/>
															<Route
																path="affiliates"
																element={<AdminAffiliatesPage />}
															/>
															<Route
																path="affiliates/:id"
																element={<AdminAffiliateDetailPage />}
															/>
															<Route
																path="analytics"
																element={<AdminAnalyticsPage />}
															/>
															<Route
																path="health"
																element={<PlatformHealthPage />}
															/>
															<Route
																path="error-logs"
																element={<ErrorLogsPage />}
															/>
															<Route
																path="data-pipeline"
																element={<DataPipelinePage />}
															/>
															<Route
																path="support"
																element={<AdminSupportPage />}
															/>
														</Route>
													</Route>

													<Route element={<ProtectedLayout />}>
														<Route path="/" element={<Index />} />
														<Route path="/hub" element={<CommunityHub />} />
														<Route path="/positions" element={<Positions />} />
														<Route
															path="/strategies"
															element={<Strategies />}
														/>
														<Route
															path="/editor/:id?"
															element={<StrategyEditorPage />}
														/>
														<Route path="/analytics" element={<Analytics />} />
														<Route path="/research" element={<Research />} />
														<Route
															path="/research/backtests/:runId"
															element={<BacktestViewerPage />}
														/>
														<Route
															path="/research/optimizations/:runId"
															element={<OptimizationViewerPage />}
														/>
														<Route
															path="/research/portfolio-backtests/:runId"
															element={<PortfolioBacktestViewer />}
														/>
														<Route
															path="/discovery"
															element={<GeneticCommandCenter />}
														/>
														<Route path="/model-lab" element={<MLCorePage />} />
														<Route path="/logs" element={<EventLog />} />
														<Route path="/settings" element={<Settings />} />
														<Route path="/account" element={<AccountPage />} />
														<Route path="/support" element={<SupportPage />} />
														<Route
															path="/leaderboard"
															element={<LeaderboardPage />}
														/>
														<Route path="/lab" element={<LaboratoryPage />} />
														{/* Diagnostic / Admin only separate pages */}
														<Route element={<AdminRoute />}>
															<Route
																path="/diagnostics/foundation-visualizer"
																element={<FoundationVisualizerPage />}
															/>
															<Route
																path="/hft"
																element={<HftDashboardPage />}
															/>
														</Route>
													</Route>

													<Route element={<AffiliateRoute />}>
														<Route element={<ProtectedLayout />}>
															<Route
																path="/affiliate-dashboard"
																element={<AffiliateDashboard />}
															/>
														</Route>
													</Route>
												</Route>

												<Route path="*" element={<NotFound />} />
											</Routes>

											{/* Global components that are not pages */}
											<OnboardingTutorial />
											<GeneDiscoveryNotification />
											<PaperModeBanner />

											{/* Components for notifications */}
											<Toaster />
											<Sonner />
										</PortfolioModeProvider>
									</SymbolSelectionSettingsProvider>
								</TooltipProvider>
							</WebSocketProvider>
						</AuthProvider>
					</BrowserRouter>
				</QueryClientProvider>
			</SidebarProvider>
		</ThemeProvider>
	);
}

export default App;
