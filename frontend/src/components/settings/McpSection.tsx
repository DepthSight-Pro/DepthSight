// src/components/settings/McpSection.tsx

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
	AlertTriangle,
	Bot,
	Check,
	Code2,
	Copy,
	Cpu,
	Key,
	Layers,
	Loader2,
	Plus,
	ShieldCheck,
	Sparkles,
	Terminal,
	Trash2,
} from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";

interface McpToolInfo {
	name: string;
	description: string;
	category: "backtest" | "strategy" | "market" | "memory" | "bot" | "portfolio" | "analytics";
}

interface PatTokenInfo {
	id: number;
	name: string;
	token_prefix: string;
	is_active: boolean;
	created_at: string;
	expires_at: string | null;
	last_used_at: string | null;
}

const MCP_TOOLS: McpToolInfo[] = [
	{
		name: "run_backtest",
		description: "Executes backtests on historical data with plan quota verification and returns key metrics.",
		category: "backtest",
	},
	{
		name: "get_strategy_schema_and_examples",
		description: "Provides full Visual Builder JSON block specifications and working examples for strategy design.",
		category: "strategy",
	},
	{
		name: "get_market_metrics",
		description: "Fetches live NATR volatility, macro trend, ML Oracle regime, and 24h volume from Screener.",
		category: "market",
	},
	{
		name: "get_historical_data_range",
		description: "Checks loaded historical market data, start/end date boundaries, timeframes, and bookDepth coverage.",
		category: "market",
	},
	{
		name: "list_strategies",
		description: "Lists all saved strategies belonging to the user's DepthSight account.",
		category: "strategy",
	},
	{
		name: "get_strategy",
		description: "Fetches full block configuration and rules of a specific saved strategy.",
		category: "strategy",
	},
	{
		name: "save_strategy",
		description: "Saves or updates a strategy with automated block validation and plan limit checks.",
		category: "strategy",
	},
	{
		name: "search_agent_memory",
		description: "Searches the persistent memory bank for historical winning rules and lessons learned.",
		category: "memory",
	},
	{
		name: "store_agent_memory",
		description: "Explicitly records newly discovered trading rules and insights into memory.",
		category: "memory",
	},
	{
		name: "get_bot_status",
		description: "Checks active live and paper trading bots, open symbols, and execution states.",
		category: "bot",
	},
	{
		name: "get_open_positions",
		description: "Monitors active bot positions: direction, entry/mark price, unrealized PnL, SL, and TP.",
		category: "portfolio",
	},
	{
		name: "get_trading_analytics",
		description: "Quantitative trading analytics: Net PnL, Win Rate %, Profit Factor, fees, and toxic hours.",
		category: "analytics",
	},
];

export const McpSection: React.FC = () => {
	const { t } = useTranslation(["settings", "common"]);
	const { toast } = useToast();
	const [copiedKey, setCopiedKey] = useState<string | null>(null);

	// PAT Tokens State
	const [patTokens, setPatTokens] = useState<PatTokenInfo[]>([]);
	const [isLoadingTokens, setIsLoadingTokens] = useState(false);
	const [isCreatingToken, setIsCreatingToken] = useState(false);
	const [newTokenName, setNewTokenName] = useState("");
	const [newTokenExpiryDays, setNewTokenExpiryDays] = useState<number | null>(90);
	const [justCreatedToken, setJustCreatedToken] = useState<string | null>(null);

	const origin = typeof window !== "undefined" ? window.location.origin : "https://app.depthsight.pro";
	const sseUrl = `${origin}/api/v1/mcp/sse`;
	const httpUrl = `${origin}/api/v1/mcp`;

	const universalUrl = justCreatedToken
		? `${sseUrl}?token=${justCreatedToken}`
		: `${sseUrl}?token=YOUR_PAT_TOKEN`;

	const copyToClipboard = (text: string, key: string) => {
		navigator.clipboard.writeText(text);
		setCopiedKey(key);
		toast({
			title: t("common:copied", "Copied to clipboard"),
			description: key,
		});
		setTimeout(() => setCopiedKey(null), 2000);
	};

	// Fetch PAT Tokens
	const fetchTokens = async () => {
		setIsLoadingTokens(true);
		try {
			const tokens = await apiClient<PatTokenInfo[]>("/mcp/tokens");
			setPatTokens(tokens || []);
		} catch (e) {
			console.error("Error fetching PAT tokens:", e);
		} finally {
			setIsLoadingTokens(false);
		}
	};

	useEffect(() => {
		fetchTokens();
	}, []);

	// Create a new PAT
	const handleCreateToken = async (e?: React.FormEvent) => {
		if (e) e.preventDefault();
		const tokenName = newTokenName.trim() || "My AI Agent";

		setIsCreatingToken(true);
		try {
			const created = await apiClient<{ token: string } & PatTokenInfo>("/mcp/tokens", {
				method: "POST",
				body: JSON.stringify({
					name: tokenName,
					expires_days: newTokenExpiryDays,
				}),
			});

			if (created && created.token) {
				setJustCreatedToken(created.token);
				setNewTokenName("");
				toast({
					title: t("settings:mcp.toasts.tokenCreated", "Personal Access Token Generated!"),
					description: t("settings:mcp.toasts.tokenCreatedDesc", "Copy your token now. It will not be shown again."),
				});
				fetchTokens();
			}
		} catch (e: any) {
			console.error("Token creation error:", e);
			toast({
				variant: "destructive",
				title: t("settings:mcp.toasts.createError", "Failed to create token"),
				description: e?.message || "Server error",
			});
		} finally {
			setIsCreatingToken(false);
		}
	};

	// Revoke a PAT
	const handleDeleteToken = async (tokenId: number) => {
		try {
			await apiClient<void>(`/mcp/tokens/${tokenId}`, {
				method: "DELETE",
			});
			toast({
				title: t("settings:mcp.toasts.tokenRevoked", "Token Revoked"),
				description: t("settings:mcp.toasts.tokenRevokedDesc", "The token has been deleted and cannot be used anymore."),
			});
			if (justCreatedToken) {
				setJustCreatedToken(null);
			}
			fetchTokens();
		} catch (e: any) {
			console.error("Error revoking token:", e);
			toast({
				variant: "destructive",
				title: t("settings:mcp.toasts.revokeError", "Error revoking token"),
				description: e?.message || "Failed to revoke token",
			});
		}
	};

	const displayTokenForSnippet = justCreatedToken || "<YOUR_PAT_TOKEN>";

	const claudeConfig = JSON.stringify(
		{
			mcpServers: {
				depthsight: {
					url: sseUrl,
					headers: {
						Authorization: `Bearer ${displayTokenForSnippet}`,
					},
				},
			},
		},
		null,
		2
	);

	const cursorConfig = JSON.stringify(
		{
			mcpServers: {
				depthsight: {
					url: sseUrl,
					headers: {
						Authorization: `Bearer ${displayTokenForSnippet}`,
					},
				},
			},
		},
		null,
		2
	);

	const codexCliCommand = `codex mcp add depthsight --url "${sseUrl}?token=${displayTokenForSnippet}"`;

	const codexConfigToml = `# ~/.codex/config.toml or .codex/config.toml
[mcp_servers.depthsight]
url = "${sseUrl}?token=${displayTokenForSnippet}"
`;

	const pythonSnippet = `import httpx

MCP_URL = "${httpUrl}"
TOKEN = "${displayTokenForSnippet}"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# 1. Handshake
resp = httpx.post(MCP_URL, headers=headers, json={
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2026-07-28", "capabilities": {}}
})
print("MCP Server:", resp.json()["result"]["serverInfo"])

# 2. Query Screener Metrics
metrics = httpx.post(MCP_URL, headers=headers, json={
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "get_market_metrics",
        "arguments": {"symbol": "BTCUSDT"}
    }
})
print("Metrics:", metrics.json()["result"]["content"][0]["text"])
`;

	return (
		<div className="space-y-6">
			{/* Overview Card */}
			<Card className="border-border/60 bg-gradient-to-br from-card via-card to-primary/5">
				<CardHeader>
					<div className="flex items-center justify-between">
						<div className="flex items-center gap-3">
							<div className="p-2.5 rounded-xl bg-primary/10 text-primary border border-primary/20">
								<Bot className="w-6 h-6" />
							</div>
							<div>
								<CardTitle className="text-xl flex items-center gap-2">
									{t("settings:mcp.title", "Model Context Protocol (WebMCP)")}
									<Badge variant="outline" className="text-xs bg-primary/10 text-primary border-primary/30">
										MCP 2026-07-28
									</Badge>
								</CardTitle>
								<CardDescription>
									{t(
										"settings:mcp.desc",
										"Connect external AI agents (Claude Desktop, Cursor IDE, LangChain, custom bots) to DepthSight tools."
									)}
								</CardDescription>
							</div>
						</div>
					</div>
				</CardHeader>
				<CardContent className="space-y-4">
					{/* Universal 1-Click All-in-One URL */}
					<div className="p-4 rounded-xl bg-primary/10 border border-primary/30 space-y-2">
						<div className="flex items-center justify-between">
							<div className="flex items-center gap-2">
								<Sparkles className="w-4 h-4 text-primary" />
								<Label className="text-sm font-semibold text-primary">
									{t("settings:mcp.universalUrl", "Universal Connection URL (1-Click All-in-One)")}
								</Label>
								<Badge variant="secondary" className="text-[10px] bg-primary/20 text-primary border-none">
									{t("settings:mcp.universalUrlBadge", "No Headers Required")}
								</Badge>
							</div>
							<Button
								variant="default"
								size="sm"
								className="gap-1.5 h-8 text-xs font-medium"
								onClick={() => copyToClipboard(universalUrl, "Universal URL")}
							>
								{copiedKey === "Universal URL" ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
								{t("common:copy", "Copy URL")}
							</Button>
						</div>
						<p className="text-xs text-muted-foreground">
							{t(
								"settings:mcp.universalUrlDesc",
								"Single self-contained URL. Works directly with any SSE-compatible client without manual header configuration."
							)}
						</p>
						<Input readOnly value={universalUrl} className="font-mono text-xs bg-background/90 selection:bg-primary" />
					</div>

					<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
						{/* SSE Endpoint */}
						<div className="space-y-2 p-3.5 rounded-lg bg-background/60 border border-border">
							<div className="flex items-center justify-between">
								<Label className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
									<Cpu className="w-3.5 h-3.5 text-primary" />
									{t("settings:mcp.sseStream", "SSE Endpoint (Claude Desktop / Cursor)")}
								</Label>
								<Button
									variant="ghost"
									size="icon"
									className="h-7 w-7"
									onClick={() => copyToClipboard(sseUrl, "SSE Endpoint")}
								>
									{copiedKey === "SSE Endpoint" ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
								</Button>
							</div>
							<Input readOnly value={sseUrl} className="font-mono text-xs bg-background/80" />
						</div>

						{/* HTTP Endpoint */}
						<div className="space-y-2 p-3.5 rounded-lg bg-background/60 border border-border">
							<div className="flex items-center justify-between">
								<Label className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
									<Terminal className="w-3.5 h-3.5 text-primary" />
									{t("settings:mcp.httpEndpoint", "Streamable HTTP Endpoint (Scripts / cURL)")}
								</Label>
								<Button
									variant="ghost"
									size="icon"
									className="h-7 w-7"
									onClick={() => copyToClipboard(httpUrl, "HTTP Endpoint")}
								>
									{copiedKey === "HTTP Endpoint" ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
								</Button>
							</div>
							<Input readOnly value={httpUrl} className="font-mono text-xs bg-background/80" />
						</div>
					</div>
				</CardContent>
			</Card>

			{/* Personal Access Tokens (PAT) Management */}
			<Card className="border-border">
				<CardHeader>
					<div className="flex items-center justify-between">
						<div>
								<CardTitle className="text-lg flex items-center gap-2">
								<Key className="w-5 h-5 text-amber-500" />
								{t("settings:mcp.patTitle", "Personal Access Tokens (PAT)")}
							</CardTitle>
							<CardDescription>
								{t(
									"settings:mcp.patDesc",
									"Long-lived, revocable authentication tokens for external AI agents. They do not expire every 30 minutes like session tokens."
								)}
							</CardDescription>
						</div>
					</div>
				</CardHeader>
				<CardContent className="space-y-6">
					{/* Just Created Token Banner */}
					{justCreatedToken && (
						<div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 space-y-2">
							<div className="flex items-center justify-between">
								<div className="flex items-center gap-2">
									<ShieldCheck className="w-5 h-5 text-emerald-500" />
									<span className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">
										{t("settings:mcp.tokenGenerated", "New Token Generated Successfully!")}
									</span>
								</div>
								<div className="flex items-center gap-2">
									<Button
										variant="outline"
										size="sm"
										className="h-8 text-xs font-medium border-emerald-500/40 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10 gap-1.5"
										onClick={() => copyToClipboard(`${sseUrl}?token=${justCreatedToken}`, "New PAT URL")}
									>
										{copiedKey === "New PAT URL" ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
										{t("settings:mcp.copyFullUrl", "Copy Full URL for Codex/Claude")}
									</Button>
									<Button
										variant="default"
										size="sm"
										className="bg-emerald-600 hover:bg-emerald-500 text-white gap-1.5 h-8 text-xs font-medium"
										onClick={() => copyToClipboard(justCreatedToken, "New PAT Token")}
									>
										{copiedKey === "New PAT Token" ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
										{t("settings:mcp.copyToken", "Copy Token Only")}
									</Button>
								</div>
							</div>
							<p className="text-xs text-muted-foreground">
								⚠️ {t("settings:mcp.tokenCopyWarning", "Make sure to copy your Personal Access Token now. You won't be able to see it again!")}
							</p>
							<Input
								readOnly
								value={justCreatedToken}
								className="font-mono text-xs bg-background/90 text-emerald-600 dark:text-emerald-400 selection:bg-emerald-500 selection:text-white"
							/>
						</div>
					)}

					{/* Create New Token Form */}
					<form onSubmit={handleCreateToken} className="p-4 rounded-xl bg-muted/40 border border-border space-y-3">
						<Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
							{t("settings:mcp.createTokenTitle", "Generate New Agent Token")}
						</Label>
						<div className="flex flex-col sm:flex-row items-center gap-3">
							<Input
								placeholder={t("settings:mcp.tokenNamePlaceholder", "e.g. My Claude Desktop, Work Cursor")}
								value={newTokenName}
								onChange={(e) => setNewTokenName(e.target.value)}
								className="text-xs"
							/>
							<select
								value={newTokenExpiryDays === null ? "never" : newTokenExpiryDays.toString()}
								onChange={(e) => setNewTokenExpiryDays(e.target.value === "never" ? null : parseInt(e.target.value))}
								className="h-9 px-3 rounded-md bg-background border border-input text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary shrink-0"
							>
								<option value="30">{t("settings:mcp.expiry.30", "30 days")}</option>
								<option value="90">{t("settings:mcp.expiry.90", "90 days")}</option>
								<option value="365">{t("settings:mcp.expiry.365", "1 year")}</option>
								<option value="never">{t("settings:mcp.expiry.never", "No expiration")}</option>
							</select>
							<Button
								type="submit"
								size="sm"
								disabled={isCreatingToken}
								className="gap-1.5 h-9 shrink-0 text-xs"
							>
								{isCreatingToken ? (
									<>
										<Loader2 className="w-3.5 h-3.5 animate-spin" />
										{t("settings:mcp.generating", "Generating...")}
									</>
								) : (
									<>
										<Plus className="w-3.5 h-3.5" />
										{t("settings:mcp.generateButton", "Generate Token")}
									</>
								)}
							</Button>
						</div>
					</form>

					{/* Active Tokens List */}
					<div className="space-y-2">
						<Label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
							{t("settings:mcp.activeTokens", "Active Tokens")} ({patTokens.length})
						</Label>
						{isLoadingTokens ? (
							<div className="text-xs text-muted-foreground p-4 text-center">{t("settings:mcp.loadingTokens", "Loading tokens...")}</div>
						) : patTokens.length === 0 ? (
							<div className="text-xs text-muted-foreground p-4 text-center rounded-lg border border-dashed border-border">
								{t("settings:mcp.noTokens", "No Personal Access Tokens created yet. Generate one above to connect your agents permanently.")}
							</div>
						) : (
							<div className="divide-y divide-border border border-border rounded-lg overflow-hidden bg-card/40">
								{patTokens.map((token) => (
									<div key={token.id} className="p-3 flex items-center justify-between gap-4">
										<div className="min-w-0">
											<div className="flex items-center gap-2">
												<span className="text-xs font-semibold text-foreground">{token.name}</span>
												<code className="text-[10px] font-mono bg-muted px-1.5 py-0.5 rounded text-muted-foreground">
													{token.token_prefix}
												</code>
											</div>
											<div className="text-[11px] text-muted-foreground mt-0.5">
												{t("settings:mcp.created", "Created:")} {new Date(token.created_at).toLocaleDateString()}
												{token.expires_at ? ` · ${t("settings:mcp.expires", "Expires:")} ${new Date(token.expires_at).toLocaleDateString()}` : ` · ${t("settings:mcp.noExpiry", "No expiry")}`}
												{token.last_used_at ? ` · ${t("settings:mcp.lastUsed", "Last used:")} ${new Date(token.last_used_at).toLocaleDateString()}` : ` · ${t("settings:mcp.neverUsed", "Never used")}`}
											</div>
										</div>
										<Button
											variant="ghost"
											size="icon"
											className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10 shrink-0"
											onClick={() => handleDeleteToken(token.id)}
											title={t("settings:mcp.revokeToken", "Revoke Token")}
										>
											<Trash2 className="w-4 h-4" />
										</Button>
									</div>
								))}
							</div>
						)}
					</div>
				</CardContent>
			</Card>

			{/* Configuration Guide & Code Snippets */}
			<Card>
				<CardHeader>
					<CardTitle className="text-lg flex items-center gap-2">
						<Code2 className="w-5 h-5 text-primary" />
						{t("settings:mcp.clientsTitle", "Quick Setup Guides")}
					</CardTitle>
					<CardDescription>
						{t("settings:mcp.clientsDesc", "Copy configuration directly into your preferred client.")}
					</CardDescription>
				</CardHeader>
				<CardContent>
					<Tabs defaultValue="claude" className="space-y-4">
						<TabsList className="grid grid-cols-4 w-full max-w-xl">
							<TabsTrigger value="claude">{t("settings:mcp.tabs.claude", "Claude")}</TabsTrigger>
							<TabsTrigger value="codex">{t("settings:mcp.tabs.codex", "OpenAI Codex")}</TabsTrigger>
							<TabsTrigger value="cursor">{t("settings:mcp.tabs.cursor", "Cursor")}</TabsTrigger>
							<TabsTrigger value="python">{t("settings:mcp.tabs.python", "Python / cURL")}</TabsTrigger>
						</TabsList>

						{/* OpenAI Codex */}
						<TabsContent value="codex" className="space-y-4">
							<div className="space-y-2">
								<div className="text-sm text-muted-foreground flex items-center justify-between">
									<span>
										{t("settings:mcp.codexOpt1", "Option 1: Quick add via Codex CLI:")}
									</span>
									<Button
										variant="outline"
										size="sm"
										className="gap-1.5"
										onClick={() => copyToClipboard(codexCliCommand, "Codex CLI")}
									>
										{copiedKey === "Codex CLI" ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
										{t("settings:mcp.copyCommand", "Copy Command")}
									</Button>
								</div>
								<pre className="p-3 rounded-lg bg-zinc-950 text-zinc-100 font-mono text-xs overflow-x-auto border border-zinc-800">
									{codexCliCommand}
								</pre>
							</div>

							<div className="space-y-2">
								<div className="text-sm text-muted-foreground flex items-center justify-between">
									<span>
										{t("settings:mcp.codexOpt2", "Option 2: Add to ~/.codex/config.toml:")}
									</span>
									<Button
										variant="outline"
										size="sm"
										className="gap-1.5"
										onClick={() => copyToClipboard(codexConfigToml, "Codex TOML")}
									>
										{copiedKey === "Codex TOML" ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
										{t("settings:mcp.copyToml", "Copy TOML")}
									</Button>
								</div>
								<pre className="p-3 rounded-lg bg-zinc-950 text-zinc-100 font-mono text-xs overflow-x-auto border border-zinc-800">
									{codexConfigToml}
								</pre>
							</div>
							<p className="text-xs text-muted-foreground">
								{t("settings:mcp.codexNote", "Works across Codex CLI, ChatGPT Desktop, and OpenAI Codex extension: in Settings > MCP / Plugins > Add Server, paste the Universal Connection URL.")}
							</p>
						</TabsContent>

						{/* Claude Desktop */}
						<TabsContent value="claude" className="space-y-3">
							<div className="text-sm text-muted-foreground flex items-center justify-between">
								<span>
									{t("settings:mcp.claudeDesc", "Add to claude_desktop_config.json:")}
								</span>
								<Button
									variant="outline"
									size="sm"
									className="gap-1.5"
									onClick={() => copyToClipboard(claudeConfig, "Claude Config")}
								>
									{copiedKey === "Claude Config" ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
									{t("settings:mcp.copyJson", "Copy JSON")}
								</Button>
							</div>
							<pre className="p-4 rounded-lg bg-zinc-950 text-zinc-100 font-mono text-xs overflow-x-auto border border-zinc-800">
								{claudeConfig}
							</pre>
						</TabsContent>

						{/* Cursor */}
						<TabsContent value="cursor" className="space-y-3">
							<div className="text-sm text-muted-foreground flex items-center justify-between">
								<span>
									{t("settings:mcp.cursorDesc", "Add to .cursor/mcp.json:")}
								</span>
								<Button
									variant="outline"
									size="sm"
									className="gap-1.5"
									onClick={() => copyToClipboard(cursorConfig, "Cursor Config")}
								>
									{copiedKey === "Cursor Config" ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
									{t("settings:mcp.copyJson", "Copy JSON")}
								</Button>
							</div>
							<pre className="p-4 rounded-lg bg-zinc-950 text-zinc-100 font-mono text-xs overflow-x-auto border border-zinc-800">
								{cursorConfig}
							</pre>
						</TabsContent>

						{/* Python */}
						<TabsContent value="python" className="space-y-3">
							<div className="text-sm text-muted-foreground flex items-center justify-between">
								<span>{t("settings:mcp.pythonDesc", "Direct Streamable HTTP JSON-RPC 2.0 call:")}</span>
								<Button
									variant="outline"
									size="sm"
									className="gap-1.5"
									onClick={() => copyToClipboard(pythonSnippet, "Python Snippet")}
								>
									{copiedKey === "Python Snippet" ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
									{t("settings:mcp.copyScript", "Copy Script")}
								</Button>
							</div>
							<pre className="p-4 rounded-lg bg-zinc-950 text-zinc-100 font-mono text-xs overflow-x-auto border border-zinc-800">
								{pythonSnippet}
							</pre>
						</TabsContent>
					</Tabs>
				</CardContent>
			</Card>

			{/* Exposed Tools Catalog */}
			<Card>
				<CardHeader>
					<div className="flex items-center justify-between">
						<div>
							<CardTitle className="text-lg flex items-center gap-2">
								<Layers className="w-5 h-5 text-primary" />
								{t("settings:mcp.toolsTitle", "Available MCP Tools Catalog")}
							</CardTitle>
							<CardDescription>
								{t("settings:mcp.toolsDesc", "Tools accessible to external AI agents via this MCP server.")}
							</CardDescription>
						</div>
						<Badge variant="secondary" className="text-xs">
							{t("settings:mcp.toolsActive", { count: MCP_TOOLS.length, defaultValue: `${MCP_TOOLS.length} Tools Active` })}
						</Badge>
					</div>
				</CardHeader>
				<CardContent>
					<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
						{MCP_TOOLS.map((tool) => (
							<div
								key={tool.name}
								className="p-3 rounded-lg border border-border bg-card/40 hover:bg-card/80 transition-colors space-y-1.5"
							>
								<div className="flex items-center justify-between">
									<span className="font-mono text-xs font-semibold text-primary">{tool.name}</span>
									<Badge variant="outline" className="text-[10px] uppercase font-mono px-1.5 py-0">
										{tool.category}
									</Badge>
								</div>
								<p className="text-xs text-muted-foreground line-clamp-2">
									{t(`settings:mcp.tools.${tool.name}`, tool.description)}
								</p>
							</div>
						))}
					</div>
				</CardContent>
			</Card>
		</div>
	);
};
