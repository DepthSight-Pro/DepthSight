// pwa/components/SideMenu.tsx

import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../constants";
import { useAuth } from "../contexts/AuthContext";
import i18n from "../i18n";
import { api } from "../services/api";
import { useAccountStore } from "../stores/accountStore";
import { type ApiKey, Screen } from "../types";
import { Logo } from "./ui/logo";

const AccountSelector: React.FC<{ t: (key: string) => string }> = ({ t }) => {
	const { selectedApiKeyId, setSelectedApiKeyId } = useAccountStore();
	const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
	const [isExpanded, setIsExpanded] = useState(false);

	useEffect(() => {
		api
			.getConfig()
			.then((config) => {
				if (config?.apiKeys) {
					setApiKeys(config.apiKeys.filter((k) => k.isActive));
				}
			})
			.catch((err) => console.error("Failed to load api keys", err));
	}, []);

	const selectedKey = apiKeys.find((k) => k.id === selectedApiKeyId);
	const label =
		selectedApiKeyId === "all"
			? t("sideMenu.allAccounts")
			: selectedKey
				? selectedKey.name
				: t("sideMenu.unknown");

	if (apiKeys.length === 0) return null;

	return (
		<div className="flex flex-col w-full p-2 rounded-lg bg-[hsl(var(--secondary))/30]">
			<button
				onClick={() => setIsExpanded(!isExpanded)}
				className="flex items-center justify-between w-full p-2 rounded-md transition hover:bg-[hsl(var(--secondary))]"
			>
				<div className="flex items-center gap-3">
					<ICONS.Wallet className="w-5 h-5 text-[hsl(var(--primary))]" />
					<div className="flex flex-col items-start">
						<span className="text-xs text-[hsl(var(--muted-foreground))]">
							{t("sideMenu.account")}
						</span>
						<span className="text-sm font-medium">{label}</span>
					</div>
				</div>
				<ICONS.ChevronDown
					className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-180" : ""}`}
				/>
			</button>

			{isExpanded && (
				<div className="mt-2 flex flex-col gap-1 pl-10">
					<button
						onClick={() => {
							setSelectedApiKeyId("all");
							setIsExpanded(false);
						}}
						className={`text-left text-sm py-2 px-3 rounded-md transition ${selectedApiKeyId === "all" ? "bg-[hsl(var(--primary))/20] text-[hsl(var(--primary))]" : "hover:bg-[hsl(var(--secondary))]"}`}
					>
						{t("sideMenu.allAccounts")}
					</button>
					{apiKeys.map((key) => (
						<button
							key={key.id}
							onClick={() => {
								setSelectedApiKeyId(key.id);
								setIsExpanded(false);
							}}
							className={`text-left text-sm py-2 px-3 rounded-md transition ${selectedApiKeyId === key.id ? "bg-[hsl(var(--primary))/20] text-[hsl(var(--primary))]" : "hover:bg-[hsl(var(--secondary))]"}`}
						>
							{key.name}
						</button>
					))}
				</div>
			)}
		</div>
	);
};

interface SideMenuProps {
	isOpen: boolean;
	onClose: () => void;
	theme: "light" | "dark";
	onToggleTheme: () => void;
	onNavigate: (screen: Screen) => void;
}

const MenuItem: React.FC<{
	icon: React.ElementType;
	label: string;
	onClick?: () => void;
}> = ({ icon: Icon, label, onClick }) => (
	<button
		onClick={onClick}
		className="flex items-center w-full gap-4 p-3 rounded-lg text-left text-base text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--secondary))]"
	>
		<Icon className="w-6 h-6 text-[hsl(var(--muted-foreground))]" />
		<span>{label}</span>
	</button>
);

const ThemeToggle: React.FC<{
	theme: "light" | "dark";
	onToggle: () => void;
	t: (key: string) => string;
}> = ({ theme, onToggle, t }) => (
	<div className="flex items-center justify-between w-full p-3 rounded-lg">
		<div className="flex items-center gap-4">
			<ICONS.Sun className="w-6 h-6 text-[hsl(var(--muted-foreground))]" />
			<span className="text-base text-[hsl(var(--foreground))]">
				{t("sideMenu.theme")}
			</span>
		</div>
		<button
			onClick={onToggle}
			className="relative inline-flex items-center h-6 rounded-full w-11 transition-colors bg-[hsl(var(--secondary))]"
			aria-label={t("sideMenu.toggleThemeLabel")}
		>
			<span
				className={`${theme === "dark" ? "translate-x-6" : "translate-x-1"} w-4 h-4 transform bg-[hsl(var(--primary))] rounded-full transition-transform flex items-center justify-center`}
			>
				{theme === "dark" && (
					<ICONS.Moon className="w-3 h-3 text-[hsl(var(--primary-foreground))]" />
				)}
				{theme === "light" && (
					<ICONS.Sun className="w-3 h-3 text-[hsl(var(--primary-foreground))]" />
				)}
			</span>
		</button>
	</div>
);

const LanguageSwitcher: React.FC<{ t: (key: string) => string }> = ({ t }) => {
	const currentLanguage = i18n.language;

	const toggleLanguage = () => {
		const newLang = currentLanguage === "en" ? "ru" : "en";
		i18n.changeLanguage(newLang);
	};

	return (
		<div className="flex items-center justify-between w-full p-3 rounded-lg">
			<div className="flex items-center gap-4">
				<ICONS.Language className="w-6 h-6 text-[hsl(var(--muted-foreground))]" />
				<span className="text-base text-[hsl(var(--foreground))]">
					{t("sideMenu.language")}
				</span>
			</div>
			<button
				onClick={toggleLanguage}
				className="relative inline-flex items-center h-6 rounded-full w-16 transition-colors bg-[hsl(var(--secondary))]"
				aria-label={t("sideMenu.toggleLanguageLabel")}
			>
				<span
					className={`${currentLanguage === "ru" ? "translate-x-9" : "translate-x-1"} w-6 h-4 transform bg-[hsl(var(--primary))] rounded-full transition-transform flex items-center justify-center text-xs font-bold text-[hsl(var(--primary-foreground))]`}
				>
					{currentLanguage === "en"
						? t("sideMenu.english")
						: t("sideMenu.russian")}
				</span>
			</button>
		</div>
	);
};

const UserProfile: React.FC = () => {
	const { user } = useAuth();
	if (!user) return null;

	return (
		<div className="flex items-center gap-3 p-3">
			<div className="w-10 h-10 bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] rounded-full flex items-center justify-center font-bold text-lg">
				{user.username.charAt(0).toUpperCase()}
			</div>
			<div>
				<div className="font-medium">{user.username}</div>
				<div className="text-sm text-[hsl(var(--muted-foreground))]">
					{user.email}
				</div>
			</div>
		</div>
	);
};

const SideMenu: React.FC<SideMenuProps> = ({
	isOpen,
	onClose,
	theme,
	onToggleTheme,
	onNavigate,
}) => {
	const { logout } = useAuth();
	const { t } = useTranslation("pwa-common");

	const handleNavigation = (screen: Screen) => {
		onNavigate(screen);
		onClose();
	};

	return (
		<>
			<div
				className={`menu-overlay fixed inset-0 bg-black/50 z-40 ${isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
				onClick={onClose}
			></div>
			<div
				className={`menu-content fixed top-0 left-0 h-full w-4/5 max-w-[300px] bg-[hsl(var(--background))] shadow-lg z-50 p-4 flex flex-col transform ${isOpen ? "translate-x-0" : "-translate-x-full"}`}
			>
				<div>
					<div className="flex justify-between items-center mb-6">
						<Logo size="lg" className="mb-8 animate-pulse" />
						<button
							onClick={onClose}
							className="w-10 h-10 flex items-center justify-center rounded-full transition hover:bg-[hsl(var(--secondary))]"
						>
							<ICONS.Close className="w-6 h-6 text-[hsl(var(--foreground))]" />
						</button>
					</div>
					<UserProfile />
					<AccountSelector t={t} />
					<hr className="my-2 border-t border-[hsl(var(--border))]" />
					<div className="flex flex-col gap-2">
						<MenuItem
							icon={ICONS.Profile}
							label={t("sideMenu.profile")}
							onClick={() => handleNavigation(Screen.Profile)}
						/>
						<MenuItem
							icon={ICONS.Settings}
							label={t("sideMenu.settings")}
							onClick={() => handleNavigation(Screen.Settings)}
						/>
					</div>
				</div>
				<div className="mt-auto">
					<hr className="my-2 border-t border-[hsl(var(--border))]" />
					<a
						href="/?view_mode=desktop"
						className="flex items-center w-full gap-4 p-3 rounded-lg text-left text-base text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--secondary))]"
					>
						<span>{t("sideMenu.fullWebsiteVersion")}</span>
					</a>
					<a
						href={
							(import.meta.env.VITE_APP_URL || "https://depthsight.pro") +
							"/terms-of-service"
						}
						target="_blank"
						rel="noopener noreferrer"
						className="flex items-center w-full gap-4 p-3 rounded-lg text-left text-base text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--secondary))]"
					>
						<span>{t("sideMenu.termsOfService")}</span>
					</a>
					<a
						href={
							(import.meta.env.VITE_APP_URL || "https://depthsight.pro") +
							"/privacy-policy"
						}
						target="_blank"
						rel="noopener noreferrer"
						className="flex items-center w-full gap-4 p-3 rounded-lg text-left text-base text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--secondary))]"
					>
						<span>{t("sideMenu.privacyPolicy")}</span>
					</a>
					<ThemeToggle theme={theme} onToggle={onToggleTheme} t={t} />
					<LanguageSwitcher t={t} />
					<hr className="my-2 border-t border-[hsl(var(--border))]" />
					<MenuItem
						icon={ICONS.Logout}
						label={t("sideMenu.logout")}
						onClick={logout}
					/>
				</div>
			</div>
		</>
	);
};

export default SideMenu;
