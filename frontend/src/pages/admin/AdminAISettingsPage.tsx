import React, { useState, useEffect } from "react";
import {
	Brain,
	Cpu,
	Save,
	Check,
	Key,
	Eye,
	EyeOff,
	Activity,
	CheckCircle2,
	AlertCircle,
	ExternalLink,
	Settings2,
	Globe,
	Clock,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	useAdminAISettings,
	useAdminUpdateAISettings,
	useAdminTestAIConnection,
} from "@/lib/api";
import type { AdminAISettings, AdminAITestResponse } from "@/types/api";

const PROVIDER_METADATA: Record<
	string,
	{
		title: string;
		desc: string;
		iconColor: string;
		badge: string;
		docsUrl: string;
		modelPresets: string[];
	}
> = {
	google: {
		title: "Google Gemini",
		desc: "Official Google GenAI SDK & Vertex AI for Gemini 3.7 Flash, Gemini 3.6, and Flash-Lite frontier series.",
		iconColor: "text-blue-500",
		badge: "Google Cloud",
		docsUrl: "https://ai.google.dev",
		modelPresets: [
			"gemini-3.7-flash",
			"gemini-3.6-flash",
			"gemini-3.5-flash-lite",
			"gemini-3.1-flash-lite",
			"gemini-2.5-pro",
			"gemini-2.5-flash",
		],
	},
	qwen: {
		title: "Qwen (DashScope / Alibaba)",
		desc: "Alibaba Cloud DashScope API with flagship Qwen 3.8-Max and open-weights Qwen 3.8 series for rapid strategy synthesis.",
		iconColor: "text-purple-500",
		badge: "Alibaba Cloud",
		docsUrl: "https://help.aliyun.com/zh/dashscope",
		modelPresets: [
			"qwen-3.8-max",
			"qwen-3.8-27b",
			"qwen-3.8-plus",
			"qwen-3.8-turbo",
			"qwen-max-latest",
			"qwen2.5-coder-32b-instruct",
		],
	},
	openrouter: {
		title: "OpenRouter",
		desc: "Unified API gateway to 100+ frontier models: Claude Opus 5, Claude Sonnet 5, DeepSeek V4 Flash, GLM 5.2, and more.",
		iconColor: "text-emerald-500",
		badge: "Multi-Model",
		docsUrl: "https://openrouter.ai/models",
		modelPresets: [
			"anthropic/claude-opus-5",
			"anthropic/claude-sonnet-5",
			"deepseek/deepseek-v4-flash",
			"z-ai/glm-5.2",
			"openai/gpt-5.6-sol",
			"google/gemini-3.7-flash",
			"qwen/qwen-3.8-max",
		],
	},
	openai: {
		title: "OpenAI / Compatible API",
		desc: "Direct OpenAI API with flagship GPT-5.6 Sol, GPT-5.5 Instant, o4-mini, and self-hosted vLLM/Ollama inference.",
		iconColor: "text-teal-500",
		badge: "OpenAI Spec",
		docsUrl: "https://platform.openai.com",
		modelPresets: [
			"gpt-5.6-sol",
			"gpt-5.6",
			"gpt-5.5-instant",
			"o4-mini",
			"o3",
			"gpt-4.5-preview",
		],
	},
	vertex_agent_builder: {
		title: "Vertex AI Agent Builder",
		desc: "Google Cloud Enterprise Generative AI Agent Builder and conversational data search pipelines.",
		iconColor: "text-amber-500",
		badge: "Enterprise",
		docsUrl: "https://cloud.google.com/generative-ai-app-builder",
		modelPresets: [
			"gemini-3.7-flash",
			"gemini-3.6-flash",
			"gemini-3.5-flash-lite",
			"gemini-2.5-pro",
		],
	},
};


export const AdminAISettingsPage: React.FC = () => {
	const { data: remoteSettings, isLoading } = useAdminAISettings();
	const { mutate: updateSettings, isPending: isUpdating } = useAdminUpdateAISettings();
	const { mutate: testConnection } = useAdminTestAIConnection();

	const [settings, setSettings] = useState<AdminAISettings | null>(null);
	const [activeTab, setActiveTab] = useState<string>("google");

	// Show/hide plaintext keys
	const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});

	// Test results per provider
	const [testResults, setTestResults] = useState<Record<string, AdminAITestResponse>>({});
	const [testingProvider, setTestingProvider] = useState<string | null>(null);

	useEffect(() => {
		if (remoteSettings) {
			setSettings(JSON.parse(JSON.stringify(remoteSettings)));
			if (remoteSettings.active_provider) {
				setActiveTab(remoteSettings.active_provider);
			}
		}
	}, [remoteSettings]);

	if (isLoading || !settings) {
		return (
			<div className="space-y-6">
				<div className="flex justify-between items-center">
					<Skeleton className="h-8 w-64" />
					<Skeleton className="h-10 w-32" />
				</div>
				<div className="grid grid-cols-1 md:grid-cols-3 gap-6">
					<Skeleton className="h-40 w-full" />
					<Skeleton className="h-40 w-full" />
					<Skeleton className="h-40 w-full" />
				</div>
				<Skeleton className="h-96 w-full" />
			</div>
		);
	}

	const toggleShowKey = (provider: string) => {
		setShowKeys((prev) => ({ ...prev, [provider]: !prev[provider] }));
	};

	const handleProviderFieldChange = (provider: string, field: string, value: any) => {
		if (!settings) return;
		const currentProviders = { ...settings.providers };
		const provData = { ...(currentProviders[provider] || {}) };
		provData[field] = value;
		currentProviders[provider] = provData;

		setSettings({
			...settings,
			providers: currentProviders,
		});
	};

	const handleSetActiveProvider = (providerKey: string) => {
		if (!settings) return;
		setSettings({
			...settings,
			active_provider: providerKey,
		});
		setActiveTab(providerKey);
	};

	const handleRunTest = (providerKey: string) => {
		if (!settings) return;
		setTestingProvider(providerKey);
		const provConfig = settings.providers[providerKey] || {};

		testConnection(
			{
				provider: providerKey,
				config: provConfig,
			},
			{
				onSuccess: (res) => {
					setTestResults((prev) => ({ ...prev, [providerKey]: res }));
					setTestingProvider(null);
				},
				onError: (err) => {
					setTestResults((prev) => ({
						...prev,
						[providerKey]: {
							success: false,
							provider: providerKey,
							latency_ms: 0,
							error: err.message,
						},
					}));
					setTestingProvider(null);
				},
			}
		);
	};

	const handleSaveAll = () => {
		if (!settings) return;
		updateSettings({
			active_provider: settings.active_provider,
			providers: settings.providers,
		});
	};

	const currentProviderConfig = settings.providers[activeTab] || {};
	const meta = PROVIDER_METADATA[activeTab] || {
		title: activeTab,
		desc: "AI Provider",
		iconColor: "text-primary",
		badge: "LLM",
		docsUrl: "#",
		modelPresets: [],
	};

	return (
		<div className="space-y-8">
			{/* Header */}
			<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
				<div>
					<h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
						<Brain className="h-8 w-8 text-primary" />
						AI & Neural Network Providers
					</h1>
					<p className="text-muted-foreground mt-1">
						Configure the active platform LLM engine for AI chat assistant, strategy generation, and market sentiment analysis.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<Button
						size="sm"
						onClick={handleSaveAll}
						disabled={isUpdating}
						className="flex items-center gap-2"
					>
						<Save className="h-4 w-4" />
						{isUpdating ? "Saving..." : "Save AI Settings"}
					</Button>
				</div>
			</div>

			{/* Active Provider Quick Selector Cards */}
			<div className="space-y-3">
				<div className="flex items-center justify-between">
					<Label className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
						Select Active AI Provider:
					</Label>
					<Badge variant="outline" className="text-xs bg-primary/5 text-primary border-primary/20">
						Active: {PROVIDER_METADATA[settings.active_provider]?.title || settings.active_provider}
					</Badge>
				</div>

				<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
					{Object.keys(PROVIDER_METADATA).map((pKey) => {
						const pMeta = PROVIDER_METADATA[pKey];
						const isSelected = settings.active_provider === pKey;
						const isConfigured = settings.providers[pKey]?.is_configured;

						return (
							<Card
								key={pKey}
								onClick={() => handleSetActiveProvider(pKey)}
								className={`cursor-pointer transition-all border-2 relative overflow-hidden ${isSelected ? "border-primary bg-primary/5 shadow-md" : "border-border hover:border-primary/40 bg-card"}`}
							>
								{isSelected && (
									<div className="absolute top-0 right-0 bg-primary text-primary-foreground p-1 rounded-bl text-[10px] font-bold uppercase tracking-wider flex items-center gap-1">
										<Check className="h-3 w-3" />
										Active
									</div>
								)}
								<CardHeader className="p-3.5 pb-2">
									<div className="flex items-center justify-between">
										<Badge variant="secondary" className="text-[10px]">
											{pMeta.badge}
										</Badge>
										{isConfigured ? (
											<span className="h-2 w-2 rounded-full bg-emerald-500" title="Key Configured" />
										) : (
											<span className="h-2 w-2 rounded-full bg-amber-500/50" title="Not Configured" />
										)}
									</div>
									<CardTitle className="text-base font-semibold mt-1">
										{pMeta.title}
									</CardTitle>
								</CardHeader>
								<CardContent className="p-3.5 pt-0">
									<span className="text-[11px] text-muted-foreground line-clamp-2">
										{pMeta.desc}
									</span>
								</CardContent>
							</Card>
						);
					})}
				</div>
			</div>

			{/* Provider Configuration Detailed Panel */}
			<div className="space-y-4">
				<Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
					<TabsList className="grid grid-cols-5 w-full">
						<TabsTrigger value="google">Google Gemini</TabsTrigger>
						<TabsTrigger value="qwen">Qwen</TabsTrigger>
						<TabsTrigger value="openrouter">OpenRouter</TabsTrigger>
						<TabsTrigger value="openai">OpenAI / Custom</TabsTrigger>
						<TabsTrigger value="vertex_agent_builder">Vertex Agent</TabsTrigger>
					</TabsList>

					{/* PROVIDER DETAILS CARD */}
					<Card className="border shadow-sm">
						<CardHeader className="pb-4 border-b">
							<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
								<div className="flex items-center gap-3">
									<div className="p-2.5 rounded-lg bg-muted/60">
										<Cpu className={`h-6 w-6 ${meta.iconColor}`} />
									</div>
									<div>
										<div className="flex items-center gap-2">
											<CardTitle className="text-xl">{meta.title}</CardTitle>
											{settings.active_provider === activeTab && (
												<Badge className="bg-primary text-primary-foreground text-xs">
													Currently Active
												</Badge>
											)}
										</div>
										<CardDescription className="text-xs mt-0.5">
											{meta.desc}
										</CardDescription>
									</div>
								</div>
								<a
									href={meta.docsUrl}
									target="_blank"
									rel="noreferrer"
									className="text-xs text-muted-foreground hover:text-primary flex items-center gap-1 self-start sm:self-center"
								>
									Documentation
									<ExternalLink className="h-3 w-3" />
								</a>
							</div>
						</CardHeader>

						<CardContent className="p-6 space-y-6">
							{/* API Key Input (Masked + Reveal) */}
							<div className="space-y-2">
								<div className="flex items-center justify-between">
									<Label className="font-semibold flex items-center gap-2">
										<Key className="h-4 w-4 text-primary" />
										API Key
									</Label>
									<div className="flex items-center gap-2">
										{currentProviderConfig.is_configured && (
											<Badge variant="outline" className="text-[11px] bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
												Configured
											</Badge>
										)}
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-7 px-2 text-xs"
											onClick={() => toggleShowKey(activeTab)}
										>
											{showKeys[activeTab] ? (
												<>
													<EyeOff className="h-3.5 w-3.5 mr-1" />
													Hide
												</>
											) : (
												<>
													<Eye className="h-3.5 w-3.5 mr-1" />
													Show
												</>
											)}
										</Button>
									</div>
								</div>

								<div className="relative">
									<Input
										type={showKeys[activeTab] ? "text" : "password"}
										placeholder={currentProviderConfig.api_key_masked || "Enter new API key to update..."}
										value={currentProviderConfig.api_key || ""}
										onChange={(e) => handleProviderFieldChange(activeTab, "api_key", e.target.value)}
										className="font-mono text-sm"
									/>
								</div>
								<span className="text-xs text-muted-foreground">
									{currentProviderConfig.api_key_masked
										? `Current key in database: ${currentProviderConfig.api_key_masked}. Leave blank to keep existing key.`
										: "Key is encrypted with Fernet (AES-128-CBC) before persistence."}
								</span>
							</div>

							{/* Model Selection & Presets */}
							<div className="space-y-2">
								<Label className="font-semibold flex items-center gap-2">
									<Settings2 className="h-4 w-4 text-primary" />
									Model Name / Identifier
								</Label>
								<div className="flex flex-col sm:flex-row gap-3">
									<Input
										value={currentProviderConfig.model || ""}
										placeholder="e.g. gemini-2.5-flash or anthropic/claude-3.7-sonnet"
										onChange={(e) => handleProviderFieldChange(activeTab, "model", e.target.value)}
										className="font-mono text-sm flex-1"
									/>
									{meta.modelPresets.length > 0 && (
										<div className="flex flex-wrap gap-1.5 items-center">
											<span className="text-xs text-muted-foreground mr-1">Presets:</span>
											{meta.modelPresets.map((preset) => (
												<Badge
													key={preset}
													variant="secondary"
													className="cursor-pointer hover:bg-primary/20 text-xs font-mono"
													onClick={() => handleProviderFieldChange(activeTab, "model", preset)}
												>
													{preset}
												</Badge>
											))}
										</div>
									)}
								</div>
							</div>

							{/* Custom Endpoint / API URL & Timeout */}
							<div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
								<div className="sm:col-span-2 space-y-2">
									<Label className="font-semibold flex items-center gap-2">
										<Globe className="h-4 w-4 text-primary" />
										API Endpoint / Base URL
									</Label>
									<Input
										value={currentProviderConfig.api_url || currentProviderConfig.endpoint || ""}
										placeholder="Default official API URL"
										onChange={(e) => {
											handleProviderFieldChange(activeTab, "api_url", e.target.value);
											handleProviderFieldChange(activeTab, "endpoint", e.target.value);
										}}
										className="font-mono text-xs"
									/>
								</div>
								<div className="space-y-2">
									<Label className="font-semibold flex items-center gap-2">
										<Clock className="h-4 w-4 text-primary" />
										Timeout (Seconds)
									</Label>
									<Input
										type="number"
										value={currentProviderConfig.timeout_seconds ?? 120}
										onChange={(e) =>
											handleProviderFieldChange(activeTab, "timeout_seconds", parseFloat(e.target.value) || 120)
										}
										className="text-sm"
									/>
								</div>
							</div>

							{/* PROVIDER-SPECIFIC EXTRA FIELDS */}
							{activeTab === "google" && (
								<div className="p-4 border rounded-lg space-y-4 bg-muted/20">
									<div className="flex items-center justify-between">
										<div>
											<Label className="font-semibold block">Use Vertex AI</Label>
											<span className="text-xs text-muted-foreground">
												Switch from Google AI Studio to Google Cloud Vertex AI enterprise environment
											</span>
										</div>
										<Switch
											checked={Boolean(currentProviderConfig.use_vertex)}
											onCheckedChange={(val) => handleProviderFieldChange("google", "use_vertex", val)}
										/>
									</div>

									{currentProviderConfig.use_vertex && (
										<div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
											<div className="space-y-1">
												<Label className="text-xs font-semibold">GCP Project ID</Label>
												<Input
													value={currentProviderConfig.gcp_project_id || ""}
													onChange={(e) => handleProviderFieldChange("google", "gcp_project_id", e.target.value)}
													placeholder="lyrical-diagram-..."
													className="text-xs"
												/>
											</div>
											<div className="space-y-1">
												<Label className="text-xs font-semibold">GCP Location</Label>
												<Input
													value={currentProviderConfig.gcp_location || "global"}
													onChange={(e) => handleProviderFieldChange("google", "gcp_location", e.target.value)}
													placeholder="us-central1 / global"
													className="text-xs"
												/>
											</div>
											<div className="space-y-1">
												<Label className="text-xs font-semibold">GCP Key Path (JSON)</Label>
												<Input
													value={currentProviderConfig.gcp_key_path || ""}
													onChange={(e) => handleProviderFieldChange("google", "gcp_key_path", e.target.value)}
													placeholder="gcp_key.json"
													className="text-xs"
												/>
											</div>
										</div>
									)}
								</div>
							)}

							{activeTab === "openrouter" && (
								<div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-4 border rounded-lg bg-muted/20">
									<div className="space-y-1">
										<Label className="text-xs font-semibold">HTTP Referer (for OpenRouter analytics)</Label>
										<Input
											value={currentProviderConfig.http_referer || ""}
											onChange={(e) => handleProviderFieldChange("openrouter", "http_referer", e.target.value)}
											placeholder="https://depthsight.pro"
											className="text-xs"
										/>
									</div>
									<div className="space-y-1">
										<Label className="text-xs font-semibold">App Title (displayed in OpenRouter dashboard)</Label>
										<Input
											value={currentProviderConfig.app_title || "DepthSight AI Assistant"}
											onChange={(e) => handleProviderFieldChange("openrouter", "app_title", e.target.value)}
											placeholder="DepthSight AI Assistant"
											className="text-xs"
										/>
									</div>
								</div>
							)}

							{activeTab === "vertex_agent_builder" && (
								<div className="grid grid-cols-1 sm:grid-cols-3 gap-4 p-4 border rounded-lg bg-muted/20">
									<div className="space-y-1">
										<Label className="text-xs font-semibold">Agent Builder ID</Label>
										<Input
											value={currentProviderConfig.agent_id || ""}
											onChange={(e) => handleProviderFieldChange("vertex_agent_builder", "agent_id", e.target.value)}
											placeholder="496179b7-..."
											className="text-xs"
										/>
									</div>
									<div className="space-y-1">
										<Label className="text-xs font-semibold">GCP Project ID</Label>
										<Input
											value={currentProviderConfig.gcp_project_id || ""}
											onChange={(e) => handleProviderFieldChange("vertex_agent_builder", "gcp_project_id", e.target.value)}
											placeholder="lyrical-diagram-..."
											className="text-xs"
										/>
									</div>
									<div className="space-y-1">
										<Label className="text-xs font-semibold">Location</Label>
										<Input
											value={currentProviderConfig.gcp_location || "global"}
											onChange={(e) => handleProviderFieldChange("vertex_agent_builder", "gcp_location", e.target.value)}
											placeholder="global"
											className="text-xs"
										/>
									</div>
								</div>
							)}

							{/* Connection Test Section */}
							<div className="border-t pt-5 space-y-3">
								<div className="flex items-center justify-between">
									<div>
										<Label className="font-semibold block">Connection Test</Label>
										<span className="text-xs text-muted-foreground">
											Sends a lightweight diagnostic prompt to verify credentials and measure live round-trip latency.
										</span>
									</div>
									<Button
										type="button"
										variant="secondary"
										size="sm"
										onClick={() => handleRunTest(activeTab)}
										disabled={testingProvider === activeTab}
										className="flex items-center gap-2"
									>
										<Activity className={`h-4 w-4 ${testingProvider === activeTab ? "animate-spin text-primary" : ""}`} />
										{testingProvider === activeTab ? "Testing..." : "Test Connection"}
									</Button>
								</div>

								{/* Test Result Display */}
								{testResults[activeTab] && (
									<div
										className={`p-3 rounded-lg border text-xs flex items-start gap-3 ${testResults[activeTab].success ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500" : "bg-destructive/10 border-destructive/30 text-destructive"}`}
									>
										{testResults[activeTab].success ? (
											<CheckCircle2 className="h-5 w-5 flex-shrink-0 mt-0.5" />
										) : (
											<AlertCircle className="h-5 w-5 flex-shrink-0 mt-0.5" />
										)}
										<div className="space-y-1">
											<div className="font-semibold flex items-center gap-2">
												<span>
													{testResults[activeTab].success ? "Connection Successful!" : "Connection Failed"}
												</span>
												<Badge variant="outline" className="text-[10px] font-mono">
													{testResults[activeTab].latency_ms} ms
												</Badge>
												{testResults[activeTab].model && (
													<Badge variant="secondary" className="text-[10px] font-mono">
														{testResults[activeTab].model}
													</Badge>
												)}
											</div>
											{testResults[activeTab].response && (
												<div className="text-muted-foreground text-[11px] font-mono bg-black/10 p-1.5 rounded">
													Response: {testResults[activeTab].response}
												</div>
											)}
											{testResults[activeTab].error && (
												<div className="text-destructive font-mono text-[11px]">
													{testResults[activeTab].error}
												</div>
											)}
										</div>
									</div>
								)}
							</div>
						</CardContent>

						<CardFooter className="p-4 bg-muted/20 border-t flex justify-between">
							<Button
								type="button"
								variant="outline"
								size="sm"
								onClick={() => handleSetActiveProvider(activeTab)}
								disabled={settings.active_provider === activeTab}
							>
								{settings.active_provider === activeTab ? "✓ Active Provider" : "Set as Active Provider"}
							</Button>
							<Button
								size="sm"
								onClick={handleSaveAll}
								disabled={isUpdating}
								className="flex items-center gap-2"
							>
								<Save className="h-4 w-4" />
								{isUpdating ? "Saving..." : "Save AI Settings"}
							</Button>
						</CardFooter>
					</Card>
				</Tabs>
			</div>
		</div>
	);
};

export default AdminAISettingsPage;
