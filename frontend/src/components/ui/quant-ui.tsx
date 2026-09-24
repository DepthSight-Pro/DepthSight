import React, { useId, useMemo, useState } from "react";
import { cn } from "@/lib/utils";

/* ---------------------------------- formatters --------------------------------- */
export const fmt = {
	usd: (n: number, d = 2) =>
		(n < 0 ? "-" : "") +
		"$" +
		Math.abs(n).toLocaleString("en-US", {
			minimumFractionDigits: d,
			maximumFractionDigits: d,
		}),
	num: (n: number, d = 2) =>
		n.toLocaleString("en-US", {
			minimumFractionDigits: d,
			maximumFractionDigits: d,
		}),
	compact: (n: number) =>
		Intl.NumberFormat("en-US", {
			notation: "compact",
			maximumFractionDigits: 1,
		}).format(n),
	pct: (n: number, d = 2) => `${n > 0 ? "+" : ""}${n.toFixed(d)}%`,
	signed: (n: number, d = 2) => `${n > 0 ? "+" : ""}${fmt.num(n, d)}`,
};

export const toneOf = (n: number) =>
	n > 0 ? "profit" : n < 0 ? "loss" : "neutral";
export const toneText = (n: number) =>
	n > 0 ? "text-emerald-400" : n < 0 ? "text-rose-400" : "text-white/60";
export const toneHex = (n: number) =>
	n > 0 ? "#10e0a0" : n < 0 ? "#ff3b5c" : "#8b93a7";

/* ---------------------------------- Radial Progress ----------------------------- */
export const Radial: React.FC<{
	value: number; // 0..1
	size?: number;
	stroke?: number;
	color?: string;
	track?: string;
	children?: React.ReactNode;
	glow?: boolean;
	className?: string;
}> = ({
	value,
	size = 64,
	stroke = 5,
	color = "#00d4ff",
	track = "rgba(255,255,255,0.06)",
	children,
	glow = true,
	className,
}) => {
	const rawId = useId();
	const id = useMemo(
		() => `rad-${rawId.replace(/[^a-zA-Z0-9_-]/g, "_")}`,
		[rawId],
	);
	const r = (size - stroke) / 2;
	const c = 2 * Math.PI * r;
	const v = Math.max(0, Math.min(1, value));
	return (
		<div
			className={cn("relative inline-flex items-center justify-center", className)}
			style={{ width: size, height: size }}
		>
			<svg width={size} height={size} className="-rotate-90 overflow-visible">
				<defs>
					<linearGradient id={id} x1="0" x2="1" y1="0" y2="1">
						<stop offset="0%" stopColor={color} />
						<stop offset="100%" stopColor="#0066ff" />
					</linearGradient>
				</defs>
				<circle
					cx={size / 2}
					cy={size / 2}
					r={r}
					stroke={track}
					strokeWidth={stroke}
					fill="none"
				/>
				{glow && (
					<circle
						cx={size / 2}
						cy={size / 2}
						r={r}
						stroke={color}
						strokeWidth={stroke + 3}
						fill="none"
						strokeDasharray={`${c * v} ${c}`}
						strokeLinecap="round"
						opacity={0.25}
					/>
				)}
				<circle
					cx={size / 2}
					cy={size / 2}
					r={r}
					stroke={`url(#${id})`}
					strokeWidth={stroke}
					fill="none"
					strokeDasharray={`${c * v} ${c}`}
					strokeLinecap="round"
					className="transition-all duration-700 ease-out"
				/>
			</svg>
			<div className="absolute inset-0 flex items-center justify-center">
				{children}
			</div>
		</div>
	);
};

/* -------------------------------- Sparkline --------------------------------- */
export const Sparkline: React.FC<{
	data: number[];
	width?: number;
	height?: number;
	color?: string;
	fill?: boolean;
	strokeWidth?: number;
	className?: string;
	baseline?: boolean;
}> = ({
	data,
	width = 96,
	height = 28,
	color,
	fill = true,
	strokeWidth = 1.5,
	className,
	baseline,
}) => {
	const id = useId();
	if (!data || data.length < 2)
		return <div style={{ width, height }} className={className} />;
	const min = Math.min(...data);
	const max = Math.max(...data);
	const range = max - min || 1;
	const stroke = color ?? toneHex(data[data.length - 1] - data[0]);
	const pts = data.map(
		(v, i) =>
			[
				(i / (data.length - 1)) * width,
				height - ((v - min) / range) * (height - 2) - 1,
			] as const,
	);
	const d = pts
		.map(
			(p, i) =>
				`${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`,
		)
		.join(" ");
	const area = `${d} L${width},${height} L0,${height} Z`;
	const baseY = height - ((data[0] - min) / range) * (height - 2) - 1;
	return (
		<svg
			width={width}
			height={height}
			viewBox={`0 0 ${width} ${height}`}
			className={cn("overflow-visible", className)}
		>
			<defs>
				<linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
					<stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
					<stop offset="100%" stopColor={stroke} stopOpacity="0" />
				</linearGradient>
			</defs>
			{fill && <path d={area} fill={`url(#${id})`} />}
			{baseline && (
				<line
					x1={0}
					x2={width}
					y1={baseY}
					y2={baseY}
					stroke="rgba(255,255,255,0.12)"
					strokeDasharray="2 3"
				/>
			)}
			<path
				d={d}
				fill="none"
				stroke={stroke}
				strokeWidth={strokeWidth}
				strokeLinejoin="round"
				strokeLinecap="round"
			/>
			<circle
				cx={pts[pts.length - 1][0]}
				cy={pts[pts.length - 1][1]}
				r={2}
				fill={stroke}
			/>
		</svg>
	);
};

/* -------------------------------- Area Chart -------------------------------- */
const AREA_W = 1000;
const AREA_PAD = { t: 12, b: 20, l: 0, r: 0 } as const;

export const AreaChart: React.FC<{
	data: number[];
	height?: number;
	color?: string;
	className?: string;
	labels?: string[];
	showGrid?: boolean;
	formatter?: (v: number) => string;
}> = ({
	data,
	height = 220,
	color = "#00d4ff",
	className,
	showGrid = true,
	formatter = (v) => fmt.usd(v, 2),
}) => {
	const rawId = useId();
	const id = useMemo(
		() => `area-${rawId.replace(/[^a-zA-Z0-9_-]/g, "_")}`,
		[rawId],
	);
	const [hover, setHover] = useState<number | null>(null);
	const W = AREA_W;
	const H = height;
	const pad = AREA_PAD;
	const { pts, min, max } = useMemo(() => {
		const min = Math.min(...data);
		const max = Math.max(...data);
		const range = max - min || 1;
		const pts = data.map(
			(v, i) =>
				[
					AREA_PAD.l + (i / (data.length - 1)) * (W - AREA_PAD.l - AREA_PAD.r),
					AREA_PAD.t + (1 - (v - min) / range) * (H - AREA_PAD.t - AREA_PAD.b),
				] as const,
		);
		return { pts, min, max };
	}, [data, H, W]);
	const path = pts
		.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`)
		.join(" ");
	const area = `${path} L${pts[pts.length - 1][0]},${H - pad.b} L${pts[0][0]},${H - pad.b} Z`;
	const gridLines = [0, 0.25, 0.5, 0.75, 1];
	const hp = hover !== null ? pts[hover] : null;
	const up = data[data.length - 1] >= data[0];

	return (
		<div className={cn("relative w-full select-none overflow-visible", className)} style={{ height }}>
			<svg
				viewBox={`0 0 ${W} ${H}`}
				preserveAspectRatio="none"
				className="w-full h-full overflow-visible"
				onMouseMove={(e) => {
					const rect = e.currentTarget.getBoundingClientRect();
					const x = ((e.clientX - rect.left) / rect.width) * W;
					const i = Math.round(
						((x - pad.l) / (W - pad.l - pad.r)) * (data.length - 1),
					);
					setHover(Math.max(0, Math.min(data.length - 1, i)));
				}}
				onMouseLeave={() => setHover(null)}
			>
				<defs>
					<linearGradient id={`${id}-a`} x1="0" x2="0" y1="0" y2="1">
						<stop offset="0%" stopColor={color} stopOpacity="0.32" />
						<stop offset="60%" stopColor={color} stopOpacity="0.05" />
						<stop offset="100%" stopColor={color} stopOpacity="0" />
					</linearGradient>
					<linearGradient id={`${id}-l`} x1="0" x2="1" y1="0" y2="0">
						<stop offset="0%" stopColor="#0066ff" />
						<stop offset="100%" stopColor={color} />
					</linearGradient>
				</defs>
				{showGrid &&
					gridLines.map((g) => (
						<line
							key={g}
							x1={0}
							x2={W}
							y1={pad.t + g * (H - pad.t - pad.b)}
							y2={pad.t + g * (H - pad.t - pad.b)}
							stroke="rgba(255,255,255,0.05)"
							strokeDasharray="3 6"
							vectorEffect="non-scaling-stroke"
						/>
					))}
				<path d={area} fill={`url(#${id}-a)`} />
				{/* Soft Outer Neon Glow without heavy/buggy GPU filter */}
				<path
					d={path}
					fill="none"
					stroke={color}
					strokeWidth={8}
					strokeLinecap="round"
					strokeLinejoin="round"
					opacity={0.12}
					vectorEffect="non-scaling-stroke"
				/>
				{/* Ambient Mid Glow */}
				<path
					d={path}
					fill="none"
					stroke={color}
					strokeWidth={4}
					strokeLinecap="round"
					strokeLinejoin="round"
					opacity={0.25}
					vectorEffect="non-scaling-stroke"
				/>
				{/* Sharp Core Gradient Line */}
				<path
					d={path}
					fill="none"
					stroke={`url(#${id}-l)`}
					strokeWidth={2}
					strokeLinejoin="round"
					strokeLinecap="round"
					vectorEffect="non-scaling-stroke"
				/>
				{hp && (
					<>
						<line
							x1={hp[0]}
							x2={hp[0]}
							y1={pad.t}
							y2={H - pad.b}
							stroke="rgba(255,255,255,0.25)"
							strokeDasharray="3 3"
							vectorEffect="non-scaling-stroke"
						/>
						<circle
							cx={hp[0]}
							cy={hp[1]}
							r={5}
							fill="#07080b"
							stroke={color}
							strokeWidth={2}
							vectorEffect="non-scaling-stroke"
						/>
					</>
				)}
			</svg>
			<div className="pointer-events-none absolute inset-y-0 right-2 flex flex-col justify-between py-2 text-[10px] font-mono text-white/30">
				<span>{formatter(max)}</span>
				<span>{formatter((max + min) / 2)}</span>
				<span>{formatter(min)}</span>
			</div>
			{hp && hover !== null && (() => {
				const isNearTop = hp[1] < 70;
				return (
				<div
					className={cn(
						"pointer-events-none absolute -translate-x-1/2 glass-strong rounded-lg px-2.5 py-1.5 text-[11px] font-mono shadow-xl z-50 whitespace-nowrap",
						isNearTop ? "translate-y-[10px]" : "-translate-y-full",
					)}
					style={{
						left: `${(hp[0] / W) * 100}%`,
						top: `${(hp[1] / H) * 100}%`,
						marginTop: isNearTop ? 10 : -10,
					}}
				>
					<div
						className={cn(
							"font-semibold",
							up ? "text-emerald-400" : "text-rose-400",
						)}
					>
						{fmt.usd(data[hover], 2)}
					</div>
					<div className="text-white/40">t-{data.length - 1 - hover}</div>
				</div>
				);
			})()}
		</div>
	);
};

/* -------------------------------- Progress bar ------------------------------ */
export const Bar: React.FC<{
	value: number;
	color?: string;
	className?: string;
	height?: number;
	striped?: boolean;
}> = ({
	value,
	color = "linear-gradient(90deg,#0066ff,#00d4ff)",
	className,
	height = 4,
	striped,
}) => (
	<div
		className={cn("w-full rounded-full bg-white/5 overflow-hidden", className)}
		style={{ height }}
	>
		<div
			className={cn(
				"h-full rounded-full transition-all duration-700",
				striped && "animate-shimmer",
			)}
			style={{
				width: `${Math.max(0, Math.min(100, value * 100))}%`,
				background: striped
					? "linear-gradient(90deg, rgba(0,102,255,.8) 0%, rgba(0,212,255,1) 50%, rgba(0,102,255,.8) 100%)"
					: color,
				backgroundSize: striped ? "200% 100%" : undefined,
			}}
		/>
	</div>
);

/* ---------------------------------- Panel ----------------------------------- */
export const Panel: React.FC<{
	title?: React.ReactNode;
	subtitle?: React.ReactNode;
	actions?: React.ReactNode;
	className?: string;
	bodyClassName?: string;
	children?: React.ReactNode;
	glow?: boolean;
	noPad?: boolean;
}> = ({
	title,
	subtitle,
	actions,
	className,
	bodyClassName,
	children,
	glow,
	noPad,
}) => (
	<section
		className={cn(
			"glass relative rounded-2xl overflow-hidden animate-fade-up",
			glow && "shadow-[0_0_60px_-20px_rgba(0,212,255,0.35)]",
			className,
		)}
	>
		{(title || actions) && (
			<header className="flex items-center justify-between gap-3 px-4 pt-3.5 pb-2.5 border-b border-white/5">
				<div className="min-w-0">
					{title && (
						<h3 className="text-[13px] font-semibold tracking-tight text-white/90 truncate">
							{title}
						</h3>
					)}
					{subtitle && (
						<p className="text-[11px] text-white/40 mt-0.5 truncate">
							{subtitle}
						</p>
					)}
				</div>
				{actions && (
					<div className="flex items-center gap-1.5 shrink-0">{actions}</div>
				)}
			</header>
		)}
		<div className={cn(!noPad && "p-4", bodyClassName)}>{children}</div>
	</section>
);

/* ---------------------------------- Badge ----------------------------------- */
type Tone = "cyan" | "azure" | "profit" | "loss" | "amber" | "neutral" | "violet";
const toneCls: Record<Tone, string> = {
	cyan: "bg-cyan/10 text-cyan border-cyan/20",
	azure: "bg-azure/15 text-[#6aa6ff] border-azure/30",
	profit: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
	loss: "bg-rose-500/10 text-rose-400 border-rose-500/20",
	amber: "bg-amber/10 text-amber border-amber/20",
	neutral: "bg-white/5 text-white/60 border-white/10",
	violet: "bg-violet-500/10 text-violet-300 border-violet-500/20",
};

export const Badge: React.FC<{
	tone?: Tone;
	children: React.ReactNode;
	className?: string;
	dot?: boolean;
	pulse?: boolean;
}> = ({ tone = "neutral", children, className, dot, pulse }) => (
	<span
		className={cn(
			"inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider leading-none",
			toneCls[tone],
			className,
		)}
	>
		{dot && (
			<span className="relative flex h-1.5 w-1.5">
				{pulse && (
					<span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
				)}
				<span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
			</span>
		)}
		{children}
	</span>
);

/* ---------------------------------- Stat ------------------------------------ */
export const Stat: React.FC<{
	label: string;
	value: React.ReactNode;
	delta?: number;
	deltaLabel?: string;
	spark?: number[];
	icon?: React.ReactNode;
	className?: string;
	mono?: boolean;
	accent?: string;
}> = ({
	label,
	value,
	delta,
	deltaLabel,
	spark,
	icon,
	className,
	mono = true,
	accent,
}) => (
	<div
		className={cn(
			"glass relative rounded-2xl p-4 overflow-hidden group hover:border-white/10 transition-colors animate-fade-up",
			className,
		)}
	>
		{accent && (
			<div
				className="pointer-events-none absolute -top-16 -right-16 h-40 w-40 rounded-full blur-3xl opacity-20 group-hover:opacity-35 transition-opacity"
				style={{ background: accent }}
			/>
		)}
		<div className="flex items-start justify-between">
			<span className="text-[11px] font-medium uppercase tracking-[0.12em] text-white/40">
				{label}
			</span>
			{icon && <span className="text-white/30">{icon}</span>}
		</div>
		<div className="mt-2 flex items-end justify-between gap-3">
			<div>
				<div
					className={cn(
						"text-[22px] leading-none font-semibold text-white tabular",
						mono && "font-mono tracking-tight",
					)}
				>
					{value}
				</div>
				{delta !== undefined && (
					<div
						className={cn(
							"mt-1.5 text-[11px] font-medium font-mono",
							toneText(delta),
						)}
					>
						{fmt.pct(delta)}{" "}
						<span className="text-white/30 font-sans">{deltaLabel}</span>
					</div>
				)}
			</div>
			{spark && <Sparkline data={spark} width={88} height={30} />}
		</div>
	</div>
);

/* --------------------------------- Exchange dot ----------------------------- */
export const ExDot: React.FC<{
	color: string;
	size?: number;
	className?: string;
}> = ({ color, size = 8, className }) => (
	<span
		className={cn("inline-block rounded-full shrink-0", className)}
		style={{
			width: size,
			height: size,
			background: color,
			boxShadow: `0 0 8px ${color}88`,
		}}
	/>
);

/* ----------------------------------- Kbd ------------------------------------ */
export const Kbd: React.FC<{ children: React.ReactNode }> = ({ children }) => (
	<kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-white/10 bg-white/5 px-1 font-mono text-[10px] text-white/50">
		{children}
	</kbd>
);

/* -------------------------------- Segmented --------------------------------- */
export function Segmented<T extends string>({
	options,
	value,
	onChange,
	size = "sm",
	className,
}: {
	options: {
		value: T;
		label: React.ReactNode;
		icon?: React.ReactNode;
		disabled?: boolean;
	}[];
	value: T;
	onChange: (v: T) => void;
	size?: "xs" | "sm" | "md";
	className?: string;
}) {
	return (
		<div
			className={cn(
				"inline-flex items-center rounded-lg bg-white/[0.04] border border-white/5 p-0.5 gap-0.5",
				size === "md" &&
					"rounded-xl p-1 gap-1 shadow-inner backdrop-blur-md",
				className,
			)}
		>
			{options.map((o) => {
				const isActive = value === o.value;
				return (
					<button
						key={o.value}
						type="button"
						disabled={o.disabled}
						onClick={() => !o.disabled && onChange(o.value)}
						className={cn(
							"group relative flex items-center font-medium transition-all whitespace-nowrap",
							size === "xs" && "gap-1 rounded px-2 py-1 text-[10px]",
							size === "sm" && "gap-1.5 rounded-md px-2.5 py-1 text-[11px]",
							size === "md" &&
								"gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm",
							isActive
								? "bg-white/[0.08] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] border border-white/10"
								: o.disabled
									? "text-white/20 cursor-not-allowed opacity-40 border border-transparent"
									: "text-white/50 hover:text-white/80 hover:bg-white/[0.03] border border-transparent",
						)}
					>
						{o.icon && (
							<span
								className={cn(
									"shrink-0 transition-all duration-200 flex items-center justify-center",
									isActive
										? "text-cyan drop-shadow-[0_0_8px_rgba(0,212,255,0.85)]"
										: "text-cyan/60 group-hover:text-cyan group-hover:drop-shadow-[0_0_6px_rgba(0,212,255,0.7)]",
								)}
							>
								{o.icon}
							</span>
						)}
						<span>{o.label}</span>
					</button>
				);
			})}
		</div>
	);
}

/* ---------------------------------- Button ---------------------------------- */
export const Btn: React.FC<
	React.ButtonHTMLAttributes<HTMLButtonElement> & {
		variant?: "primary" | "ghost" | "outline" | "danger" | "subtle";
		size?: "xs" | "sm" | "md";
		icon?: React.ReactNode;
	}
> = ({
	variant = "outline",
	size = "sm",
	icon,
	className,
	children,
	...rest
}) => (
	<button
		type="button"
		{...rest}
		className={cn(
			"inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all active:scale-[0.98] disabled:opacity-40 disabled:pointer-events-none",
			size === "xs" && "h-6 px-2 text-[10px]",
			size === "sm" && "h-7.5 px-2.5 text-[11px]",
			size === "md" && "h-9 px-4 text-xs",
			variant === "primary" &&
				"bg-gradient-to-r from-azure to-cyan text-white shadow-[0_0_24px_-6px_rgba(0,212,255,0.8)] hover:shadow-[0_0_32px_-4px_rgba(0,212,255,0.9)] hover:brightness-110",
			variant === "outline" &&
				"border border-white/10 bg-white/[0.03] text-white/80 hover:bg-white/[0.07] hover:border-white/20 hover:text-white",
			variant === "ghost" && "text-white/60 hover:text-white hover:bg-white/5",
			variant === "subtle" &&
				"bg-cyan/10 text-cyan border border-cyan/20 hover:bg-cyan/15",
			variant === "danger" &&
				"border border-rose-500/30 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20",
			className,
		)}
	>
		{icon}
		{children}
	</button>
);

/* --------------------------------- Heatmap ---------------------------------- */
export const Heatmap: React.FC<{
	rows: { symbol: string; cells: number[] }[];
	className?: string;
}> = ({ rows, className }) => {
	const [hov, setHov] = useState<{ r: number; c: number } | null>(null);
	if (!rows || rows.length === 0) return null;
	const maxAbs =
		Math.max(...rows.flatMap((r) => r.cells.map((c) => Math.abs(c)))) || 1;

	return (
		<div className={cn("relative", className)}>
			<div
				className="grid gap-[3px]"
				style={{
					gridTemplateColumns: `44px repeat(${rows[0]?.cells?.length || 24}, minmax(0,1fr))`,
				}}
			>
				{rows.map((r, ri) => (
					<React.Fragment key={r.symbol}>
						<div className="text-[10px] font-mono text-white/40 flex items-center">
							{r.symbol}
						</div>
						{r.cells.map((v, ci) => {
							const t = Math.abs(v) / maxAbs;
							const bg =
								v >= 0
									? `rgba(16,224,160,${0.08 + t * 0.75})`
									: `rgba(244,63,94,${0.08 + t * 0.75})`;
							const active = hov && hov.r === ri && hov.c === ci;
							return (
								<div
									key={ci}
									onMouseEnter={() => setHov({ r: ri, c: ci })}
									onMouseLeave={() => setHov(null)}
									className={cn(
										"aspect-square rounded-[3px] transition-transform duration-150 cursor-pointer",
										active && "scale-125 ring-1 ring-white/60 z-10",
									)}
									style={{ background: bg }}
									title={`${r.symbol} ${ci}:00 · ${fmt.pct(v)}`}
								/>
							);
						})}
					</React.Fragment>
				))}
				<div />
				{rows[0]?.cells?.map((_, i) => (
					<div
						key={i}
						className="text-[9px] font-mono text-white/25 text-center"
					>
						{i % 4 === 0 ? `${i}h` : ""}
					</div>
				))}
			</div>
			{hov && rows[hov.r] && (
				<div className="absolute top-0 right-0 glass-strong rounded-md px-2 py-1 text-[10px] font-mono shadow-lg border border-white/10">
					{rows[hov.r].symbol} · {hov.c}:00 →{" "}
					<span className={toneText(rows[hov.r].cells[hov.c])}>
						{fmt.pct(rows[hov.r].cells[hov.c])}
					</span>
				</div>
			)}
		</div>
	);
};

/* ------------------------------- Table helpers ------------------------------ */
export const Th: React.FC<{
	children?: React.ReactNode;
	className?: string;
	right?: boolean;
}> = ({ children, className, right }) => (
	<th
		className={cn(
			"px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/35 whitespace-nowrap",
			right ? "text-right" : "text-left",
			className,
		)}
	>
		{children}
	</th>
);

export const Td: React.FC<{
	children?: React.ReactNode;
	className?: string;
	right?: boolean;
	mono?: boolean;
}> = ({ children, className, right, mono }) => (
	<td
		className={cn(
			"px-3 py-2.5 text-[12px] text-white/80 whitespace-nowrap",
			right && "text-right",
			mono && "font-mono tabular",
			className,
		)}
	>
		{children}
	</td>
);

/* ---------------------------------- Divider --------------------------------- */
export const SectionLabel: React.FC<{
	children: React.ReactNode;
	className?: string;
}> = ({ children, className }) => (
	<div
		className={cn(
			"text-[10px] font-semibold uppercase tracking-[0.18em] text-white/30",
			className,
		)}
	>
		{children}
	</div>
);

/* --------------------------------- Toggle ----------------------------------- */
export const Toggle: React.FC<{
	checked: boolean;
	onChange: (v: boolean) => void;
	danger?: boolean;
}> = ({ checked, onChange, danger }) => (
	<button
		type="button"
		onClick={() => onChange(!checked)}
		className={cn(
			"relative h-5 w-9 rounded-full border transition-all",
			checked
				? danger
					? "bg-rose-500/30 border-rose-500/50 shadow-[0_0_14px_-2px_rgba(244,63,94,0.6)]"
					: "bg-cyan/25 border-cyan/50 shadow-[0_0_14px_-2px_rgba(0,212,255,0.7)]"
				: "bg-white/5 border-white/10",
		)}
	>
		<span
			className={cn(
				"absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all",
				checked
					? danger
						? "left-[18px] bg-rose-500"
						: "left-[18px] bg-cyan"
					: "left-0.5 bg-white/40",
			)}
		/>
	</button>
);

