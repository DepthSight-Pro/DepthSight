// pwa/screens/ProfileScreen.tsx

import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSwipeable } from "react-swipeable";
import Achievements from "../components/Achievements";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "../components/Card";
import Progress from "../components/Progress";
import Tabs from "../components/Tabs";
import { Logo } from "../components/ui/logo";
import { ICONS } from "../constants";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import type {
	AccountStatusData,
	PaperWalletData,
	Plan,
	User,
	UserGenesResponse,
} from "../types";

type FeedbackState = { type: "success" | "error"; message: string } | null;

interface ConfirmationDialogProps {
	open: boolean;
	title: string;
	description?: string;
	confirmLabel?: string;
	cancelLabel?: string;
	loading?: boolean;
	onConfirm: () => void;
	onCancel: () => void;
}

const ConfirmationDialog: React.FC<ConfirmationDialogProps> = ({
	open,
	title,
	description,
	confirmLabel = "Confirm",
	cancelLabel = "Cancel",
	loading,
	onConfirm,
	onCancel,
}) => {
	const { t } = useTranslation("pwa-common");
	if (!open) return null;

	return (
		<>
			<div
				className={`fixed inset-0 z-40 bg-black/50 transition-opacity duration-300 ${open ? "opacity-100" : "opacity-0 pointer-events-none"}`}
				onClick={() => {
					if (!loading) {
						onCancel();
					}
				}}
			/>
			<div
				className={`fixed top-1/2 left-1/2 z-50 w-[90%] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-3xl bg-[hsl(var(--card))] p-6 shadow-[-4px_0_20px_rgba(0,0,0,0.1)] transition-all ${open ? "scale-100 opacity-100" : "scale-95 opacity-0"}`}
			>
				<h3 className="text-lg font-semibold text-[hsl(var(--card-foreground))]">
					{title}
				</h3>
				{description && (
					<p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
						{description}
					</p>
				)}
				<div className="mt-6 flex gap-3">
					<button
						className="flex-1 rounded-lg bg-[hsl(var(--secondary))] px-4 py-2 text-sm font-medium text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-60"
						onClick={onCancel}
						disabled={loading}
					>
						{cancelLabel}
					</button>
					<button
						className="flex-1 rounded-lg bg-[hsl(var(--destructive))] px-4 py-2 text-sm font-medium text-[hsl(var(--destructive-foreground))] transition hover:opacity-90 disabled:opacity-60"
						onClick={onConfirm}
						disabled={loading}
					>
						{loading ? t("profile.pleaseWait") : confirmLabel}
					</button>
				</div>
			</div>
		</>
	);
};

interface PricingModalProps {
	isOpen: boolean;
	onClose: () => void;
	currentPlan?: string | null;
}

const PricingModal: React.FC<PricingModalProps> = ({
	isOpen,
	onClose,
	currentPlan,
}) => {
	const [plans, setPlans] = useState<Plan[]>([]);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);
	const { t } = useTranslation("pwa-common");

	const fetchPlans = useCallback(async () => {
		try {
			setLoading(true);
			setError(null);
			const data = await api.getPlans();
			setPlans(data);
		} catch (err) {
			setError(err instanceof Error ? err.message : t("profile.failedToLoadPlans"));
		} finally {
			setLoading(false);
		}
	}, [t]);

	useEffect(() => {
		if (isOpen && plans.length === 0) {
			const timer = setTimeout(() => {
				fetchPlans();
			}, 0);
			return () => clearTimeout(timer);
		}
		if (!isOpen) {
			const timer = setTimeout(() => {
				setSelectedPlan(null);
				setError(null);
			}, 0);
			return () => clearTimeout(timer);
		}
	}, [isOpen, plans.length, fetchPlans]);

	const handleSelectPlan = async (plan: Plan) => {
		if (submitting || plan.key === currentPlan || plan.key === "free") {
			return;
		}

		try {
			setSubmitting(true);
			setSelectedPlan(plan.key);
			const response = await api.createPayment({ plan_name: plan.key });
			if (response?.invoice_url) {
				window.location.assign(response.invoice_url);
			} else {
				setError(t("profile.failedToOpenPaymentPage"));
			}
		} catch (err) {
			setError(err instanceof Error ? err.message : t("profile.failedToInitiatePayment"));
		} finally {
			setSubmitting(false);
		}
	};

	if (!isOpen) return null;

	return (
		<>
			<div
				className={`fixed inset-0 z-40 bg-black/50 transition-opacity duration-300 ${isOpen ? "opacity-100" : "opacity-0 pointer-events-none"}`}
				onClick={() => {
					if (!submitting) {
						onClose();
					}
				}}
			/>
			<div
				className={`fixed top-1/2 left-1/2 z-50 w-[95%] max-w-3xl -translate-x-1/2 -translate-y-1/2 rounded-3xl bg-[hsl(var(--card))] p-4 md:p-6 shadow-[-4px_0_24px_rgba(0,0,0,0.18)] transition-all ${isOpen ? "scale-100 opacity-100" : "scale-95 opacity-0"} flex flex-col max-h-[90vh]`}
			>
				<div className="mb-4 flex items-start justify-between gap-4">
					<div>
						<h3 className="text-2xl font-semibold text-[hsl(var(--card-foreground))]">
							{t("profile.choosePlan")}
						</h3>
						<p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
							{t("profile.upgradePlanDescription")}
						</p>
					</div>
					<button
						className="rounded-full bg-[hsl(var(--secondary))] p-2 text-[hsl(var(--secondary-foreground))] transition hover:opacity-80"
						onClick={onClose}
						disabled={submitting}
					>
						<ICONS.Close className="h-5 w-5" />
					</button>
				</div>
				<div className="flex-1 overflow-y-auto pr-1 space-y-4">
					{error && (
						<div className="rounded-lg bg-[hsl(var(--loss))]/15 p-3 text-sm text-[hsl(var(--loss))]">
							{error}
						</div>
					)}

					{loading ? (
						<div className="flex min-h-[160px] items-center justify-center">
							<Logo size="lg" className="mb-8 animate-pulse" />
						</div>
					) : (
						<div className="grid gap-4 md:grid-cols-3">
							{plans.map((plan) => {
								const isCurrent = plan.key === currentPlan;
								const isDisabled = isCurrent || plan.key === "free";
								const isPending = submitting && selectedPlan === plan.key;

								return (
									<div
										key={plan.key}
										className={`flex h-full flex-col rounded-2xl border p-4 transition ${
											isCurrent
												? "border-[hsl(var(--primary))] ring-2 ring-[hsl(var(--primary))]"
												: "border-[hsl(var(--border))]"
										}`}
									>
										<div className="flex items-baseline justify-between">
											<h4 className="text-lg font-semibold text-[hsl(var(--card-foreground))]">
												{plan.name}
											</h4>
											<span className="text-xl font-bold text-[hsl(var(--primary))]">
												${plan.price_usd}
												<span className="text-xs font-normal text-[hsl(var(--muted-foreground))]">
													{t("profile.perMonth")}
												</span>
											</span>
										</div>
										<p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
											{plan.description}
										</p>
										<ul className="mt-4 space-y-1 text-xs text-[hsl(var(--muted-foreground))]">
											{plan.features.map((feature, index) => (
												<li key={index} className="flex items-start gap-2">
													<span className="mt-1 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-[hsl(var(--primary))]" />
													<span>{feature}</span>
												</li>
											))}
										</ul>
										<button
											className="mt-auto w-full rounded-lg bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] transition hover:opacity-90 disabled:opacity-60"
											onClick={() => handleSelectPlan(plan)}
											disabled={isDisabled || submitting}
										>
											{isCurrent
												? t("profile.currentPlanLabel")
												: isPending
													? t("profile.transitioning")
													: t("profile.select")}
										</button>
									</div>
								);
							})}
						</div>
					)}
				</div>
				<div className="pt-3 text-center text-xs text-[hsl(var(--muted-foreground))]">
					{t("profile.continueAgreeing")}{" "}
					<a
						href={
							(import.meta.env.VITE_APP_URL || "https://depthsight.pro") +
							"/terms-of-service"
						}
						target="_blank"
						rel="noopener noreferrer"
						className="underline text-[hsl(var(--primary))] hover:opacity-80"
					>
						{t("profile.termsAndConditions")}
					</a>{" "}
					{t("profile.and")}{" "}
					<a
						href={
							(import.meta.env.VITE_APP_URL || "https://depthsight.pro") +
							"/privacy-policy"
						}
						target="_blank"
						rel="noopener noreferrer"
						className="underline text-[hsl(var(--primary))] hover:opacity-80"
					>
						{t("profile.privacyPolicy")}
					</a>
					.
				</div>
			</div>
		</>
	);
};

const copyTextToClipboard = async (text: string): Promise<boolean> => {
	try {
		if (navigator?.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {
		// Fallback below
	}

	try {
		const textarea = document.createElement("textarea");
		textarea.value = text;
		textarea.style.position = "fixed";
		textarea.style.opacity = "0";
		document.body.appendChild(textarea);
		textarea.focus();
		textarea.select();
		const successful = document.execCommand("copy");
		document.body.removeChild(textarea);
		return successful;
	} catch {
		return false;
	}
};

const ProfileScreen = () => {
	const [accountStatus, setAccountStatus] = useState<AccountStatusData | null>(
		null,
	);
	const [paperWallet, setPaperWallet] = useState<PaperWalletData[] | null>(
		null,
	);
	const [genes, setGenes] = useState<UserGenesResponse | null>(null);
	const [user, setUser] = useState<User | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [isPricingModalOpen, setIsPricingModalOpen] = useState(false);
	const [showResetConfirm, setShowResetConfirm] = useState(false);
	const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
	const [actionLoading, setActionLoading] = useState<"reset" | "delete" | null>(
		null,
	);
	const [feedback, setFeedback] = useState<FeedbackState>(null);
	const [copiedField, setCopiedField] = useState<"code" | "link" | null>(null);
	const { logout } = useAuth();
	const { t } = useTranslation("pwa-common");
	const [activeTab, setActiveTab] = useState(0);

	const swipeHandlers = useSwipeable({
		onSwipedLeft: () => setActiveTab(1),
		onSwipedRight: () => setActiveTab(0),
		preventScrollOnSwipe: true,
		trackMouse: true,
	});

	const refreshAccountSummary = useCallback(async () => {
		const [statusData, walletData] = await Promise.all([
			api.getAccountStatus(),
			api.getPaperWallet(),
		]);
		setAccountStatus(statusData);
		setPaperWallet(walletData);
	}, []);

	const loadData = useCallback(async () => {
		try {
			setLoading(true);
			setError(null);
			setFeedback(null);
			const summaryPromise = refreshAccountSummary();
			const [, genesData, currentUser] = await Promise.all([
				summaryPromise,
				api.getMyGenes(),
				api.getMe(),
			]);
			setGenes(genesData);
			setUser(currentUser);
		} catch (err) {
			setError(err instanceof Error ? err.message : t("profile.failedToLoadProfileData"));
		} finally {
			setLoading(false);
		}
	}, [refreshAccountSummary, t]);

	useEffect(() => {
		const timer = setTimeout(() => {
			loadData();
		}, 0);
		return () => clearTimeout(timer);
	}, [loadData]);

	const usdtBalance =
		paperWallet?.find((a) => a.asset === "USDT")?.balance ?? 0;
	const referralLink = user?.referralCode
		? `${window.location.origin}/register?ref=${user.referralCode}`
		: "";

	const handleResetConfirm = async () => {
		try {
			setActionLoading("reset");
			setFeedback(null);
			await api.resetPaperAccount();
			await refreshAccountSummary();
			setFeedback({
				type: "success",
				message: t("profile.paperAccountResetSuccess"),
			});
		} catch (err) {
			setFeedback({
				type: "error",
				message: err instanceof Error ? err.message : t("profile.failedToResetPaperAccount"),
			});
		} finally {
			setActionLoading(null);
			setShowResetConfirm(false);
		}
	};

	const handleDeleteConfirm = async () => {
		try {
			setActionLoading("delete");
			setFeedback(null);
			await api.deleteAccount();
			setFeedback({ type: "success", message: t("profile.accountDeleted") });
			setShowDeleteConfirm(false);
			logout();
		} catch (err) {
			setFeedback({
				type: "error",
				message: err instanceof Error ? err.message : t("profile.failedToDeleteAccount"),
			});
		} finally {
			setActionLoading(null);
		}
	};

	const handleCopy = async (value: string, field: "code" | "link") => {
		if (!value) return;
		setFeedback(null);
		const success = await copyTextToClipboard(value);
		if (success) {
			setCopiedField(field);
			setFeedback({ type: "success", message: t("profile.copiedToClipboard") });
			setTimeout(() => setCopiedField(null), 2000);
		} else {
			setFeedback({ type: "error", message: t("profile.failedToCopyValue") });
		}
	};

	const accountContent = (
		<div className="space-y-4">
			{/* My Plan */}
			<Card>
				<CardHeader>
					<CardTitle>{t("profile.myPlan")}</CardTitle>
					<CardDescription>
						{accountStatus?.planExpiresAt
							? t("profile.planActiveUntil", {
									date: new Date(
										accountStatus.planExpiresAt,
									).toLocaleDateString(),
								})
							: t("profile.noActivePlan")}
					</CardDescription>
				</CardHeader>
				<CardContent className="flex items-center justify-between">
					<span className="text-xl font-bold capitalize text-[hsl(var(--card-foreground))]">
						{accountStatus?.planName || "free"}
					</span>
					<button
						className="rounded-lg bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] transition hover:opacity-90 disabled:opacity-60"
						onClick={() => setIsPricingModalOpen(true)}
						disabled
					>
						{t("profile.changePlan")}
					</button>
				</CardContent>
			</Card>

			{/* Paper Account */}
			<Card>
				<CardHeader>
					<CardTitle>{t("profile.paperAccount")}</CardTitle>
				</CardHeader>
				<CardContent className="flex items-center justify-between">
					<span className="text-xl font-mono font-bold text-[hsl(var(--card-foreground))]">
						$
						{usdtBalance.toLocaleString("en-US", {
							minimumFractionDigits: 2,
							maximumFractionDigits: 2,
						})}
					</span>
					<button
						className="rounded-lg bg-[hsl(var(--secondary))] px-4 py-2 text-sm font-medium text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-60"
						onClick={() => setShowResetConfirm(true)}
						disabled={actionLoading === "reset"}
					>
						{actionLoading === "reset"
							? t("profile.resetting")
							: t("profile.reset")}
					</button>
				</CardContent>
			</Card>

			{/* Quotas */}
			<Card>
				<CardHeader>
					<CardTitle>{t("profile.quotas")}</CardTitle>
				</CardHeader>
				<CardContent className="space-y-2">
					{accountStatus?.quotas?.map((quota) => (
						<div key={quota.name}>
							<div className="flex justify-between text-sm text-[hsl(var(--card-foreground))]">
								<span>{t(`quotas.${quota.name}`, quota.name)}</span>
								<span>
									{quota.used} /{" "}
									{quota.limit === -1 ? t("profile.unlimited") : quota.limit}
								</span>
							</div>
							{quota.limit !== -1 && (
								<Progress value={(quota.used / quota.limit) * 100} />
							)}
						</div>
					))}
				</CardContent>
			</Card>

			{/* Referrals */}
			<Card>
				<CardHeader>
					<CardTitle>{t("profile.referrals")}</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="mt-2">
						<label className="text-sm font-medium text-[hsl(var(--card-foreground))]">
							{t("profile.referralCode")}
						</label>
						<div className="flex items-center space-x-2 mt-1">
							<input
								readOnly
								value={user?.referralCode || ""}
								className="w-full p-2 border rounded bg-[hsl(var(--background))] border-[hsl(var(--border))] text-[hsl(var(--foreground))]"
							/>
							<button
								className="rounded-lg bg-[hsl(var(--secondary))] px-4 py-2 text-sm font-medium text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-60"
								onClick={() => handleCopy(user?.referralCode || "", "code")}
								disabled={!user?.referralCode}
							>
								{copiedField === "code"
									? t("profile.copied")
									: t("profile.copy")}
							</button>
						</div>
						{copiedField === "code" && (
							<div className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
								{t("profile.codeCopied")}
							</div>
						)}
					</div>
					<div className="mt-2">
						<label className="text-sm font-medium text-[hsl(var(--card-foreground))]">
							{t("profile.referralLink")}
						</label>
						<div className="flex items-center space-x-2 mt-1">
							<input
								readOnly
								value={referralLink}
								className="w-full p-2 border rounded bg-[hsl(var(--background))] border-[hsl(var(--border))] text-[hsl(var(--foreground))]"
							/>
							<button
								className="rounded-lg bg-[hsl(var(--secondary))] px-4 py-2 text-sm font-medium text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-60"
								onClick={() => handleCopy(referralLink, "link")}
								disabled={!referralLink}
							>
								{copiedField === "link"
									? t("profile.copied")
									: t("profile.copy")}
							</button>
						</div>
						{copiedField === "link" && (
							<div className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
								{t("profile.linkCopied")}
							</div>
						)}
					</div>
				</CardContent>
			</Card>

			{/* Genetics Laboratory */}
			<Card>
				<CardHeader>
					<CardTitle>{t("profile.geneticsLaboratory")}</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="flex items-center justify-between">
						<span className="text-sm text-[hsl(var(--muted-foreground))]">
							{t("profile.genesDiscovered")}
						</span>
						<span className="text-2xl font-bold text-green-500">
							{genes?.total || 0}
						</span>
					</div>
					<div className="flex justify-around pt-2">
						{/* Rarity breakdown */}
					</div>
				</CardContent>
			</Card>

			{/* Danger Zone */}
			<Card className="border-red-500">
				<CardHeader>
					<CardTitle className="text-red-500">
						{t("profile.dangerZone")}
					</CardTitle>
				</CardHeader>
				<CardContent>
					<div>
						<p className="font-semibold text-[hsl(var(--card-foreground))]">
							{t("profile.deleteAccountTitle")}
						</p>
						<p className="text-sm text-[hsl(var(--muted-foreground))]">
							{t("profile.deleteAccountDescription")}
						</p>
					</div>
					<div className="flex justify-end mt-4">
						<button
							className="rounded-lg bg-[hsl(var(--destructive))] px-4 py-2 text-sm font-medium text-[hsl(var(--destructive-foreground))] transition hover:opacity-90 disabled:opacity-60"
							onClick={() => setShowDeleteConfirm(true)}
							disabled={actionLoading === "delete"}
						>
							{actionLoading === "delete"
								? t("profile.deleting")
								: t("profile.deleteAccount")}
						</button>
					</div>
				</CardContent>
			</Card>
		</div>
	);

	if (loading) {
		return (
			<div className="flex justify-center items-center min-h-screen">
				<Logo size="lg" className="mb-8 animate-pulse" />
			</div>
		);
	}

	if (error) {
		return (
			<div className="p-4 text-red-500">
				{t("profile.error")}
				{error}
			</div>
		);
	}

	return (
		<div className="p-4 space-y-4" {...swipeHandlers}>
			{feedback && (
				<div
					className={`rounded-lg p-3 text-sm ${
						feedback.type === "success"
							? "bg-[hsl(var(--profit))]/15 text-[hsl(var(--profit))]"
							: "bg-[hsl(var(--loss))]/15 text-[hsl(var(--loss))]"
					}`}
				>
					{feedback.message}
				</div>
			)}
			<Tabs
				activeTab={activeTab}
				setActiveTab={setActiveTab}
				tabs={[
					{ label: t("profile.accountTab"), content: accountContent },
					{ label: t("profile.achievementsTab"), content: <Achievements /> },
				]}
			/>

			<PricingModal
				isOpen={isPricingModalOpen}
				onClose={() => setIsPricingModalOpen(false)}
				currentPlan={accountStatus?.planName}
			/>

			<ConfirmationDialog
				open={showResetConfirm}
				onCancel={() => setShowResetConfirm(false)}
				onConfirm={handleResetConfirm}
				loading={actionLoading === "reset"}
				title={t("profile.confirmResetTitle")}
				description={t("profile.confirmResetMessage")}
				confirmLabel={t("profile.resetAccount")}
			/>

			<ConfirmationDialog
				open={showDeleteConfirm}
				onCancel={() => setShowDeleteConfirm(false)}
				onConfirm={handleDeleteConfirm}
				loading={actionLoading === "delete"}
				title={t("profile.confirmDeleteTitle")}
				description={t("profile.confirmDeleteMessage")}
				confirmLabel={t("profile.deleteMyAccount")}
			/>
		</div>
	);
};

export default ProfileScreen;
