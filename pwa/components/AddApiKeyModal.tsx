// pwa/components/AddApiKeyModal.tsx

import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "./ui/Input";

interface AddApiKeyModalProps {
	isOpen: boolean;
	onClose: () => void;
	onAdd: (apiKey: string, apiSecret: string) => void;
	isLoading: boolean;
}

const AddApiKeyModal: React.FC<AddApiKeyModalProps> = ({
	isOpen,
	onClose,
	onAdd,
	isLoading,
}) => {
	const { t } = useTranslation("pwa-common");
	const [apiKey, setApiKey] = useState("");
	const [apiSecret, setApiSecret] = useState("");

	const handleSubmit = () => {
		if (apiKey && apiSecret) {
			onAdd(apiKey, apiSecret);
		}
	};

	if (!isOpen) return null;

	return (
		<>
			<div
				className={`fixed inset-0 bg-black/50 z-40 transition-opacity duration-300 ${isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
				onClick={onClose}
				onKeyDown={(e) => {
					if (e.key === "Enter" || e.key === " ") {
						onClose();
					}
				}}
				role="button"
				tabIndex={0}
				aria-label={t("buttons.close")}
			></div>
			<div
				className={`fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[90%] max-w-md bg-[hsl(var(--card))] rounded-3xl shadow-[-4px_0_20px_rgba(0,0,0,0.1)] p-6 z-50 transition-all duration-300 ease-out ${isOpen ? "scale-100 opacity-100" : "scale-95 opacity-0"}`}
			>
				<h2 className="text-xl font-medium mb-1 text-[hsl(var(--card-foreground))]">
					{t("addApiKeyModal.title")}
				</h2>
				<div className="p-4">
					<div className="mb-4">
						<label
							htmlFor="apiKey"
							className="block text-sm font-medium text-[hsl(var(--foreground))] mb-2"
						>
							{t("addApiKeyModal.apiKeyLabel")}
						</label>
						<Input
							id="apiKey"
							type="text"
							value={apiKey}
							onChange={(e) => setApiKey(e.target.value)}
							placeholder={t("addApiKeyModal.apiKeyPlaceholder")}
							className="w-full"
						/>
					</div>
					<div className="mb-4">
						<label
							htmlFor="apiSecret"
							className="block text-sm font-medium text-[hsl(var(--foreground))] mb-2"
						>
							{t("addApiKeyModal.apiSecretLabel")}
						</label>
						<Input
							id="apiSecret"
							type="password"
							value={apiSecret}
							onChange={(e) => setApiSecret(e.target.value)}
							placeholder={t("addApiKeyModal.apiSecretPlaceholder")}
							className="w-full"
						/>
					</div>
					<div className="flex justify-end gap-2">
						<button
							type="button"
							onClick={onClose}
							className="px-4 py-2 rounded-lg border"
						>
							{t("buttons.cancel")}
						</button>
						<button
							type="button"
							onClick={handleSubmit}
							className="px-4 py-2 rounded-lg bg-blue-500 text-white"
							disabled={isLoading}
						>
							{isLoading ? t("buttons.adding") : t("buttons.add")}
						</button>
					</div>
				</div>
			</div>
		</>
	);
};

export default AddApiKeyModal;
