// src/components/ui/logo.tsx
import type React from "react"; // 1. Import the useId hook
import { useId } from "react";

interface LogoProps extends React.SVGProps<SVGSVGElement> {
	iconOnly?: boolean;
}

export function Logo({ iconOnly = false, ...props }: LogoProps) {
	// 2. Generate a unique base ID for this component instance
	const uniqueInstanceId = useId();
	const gradientId = `techGradient-${uniqueInstanceId}`;
	const pulseId = `pulseGradient-${uniqueInstanceId}`;
	const glowId = `glow-${uniqueInstanceId}`;

	return (
		<svg
			viewBox={iconOnly ? "0 0 75 75" : "0 0 320 100"}
			xmlns="http://www.w3.org/2000/svg"
			shapeRendering="geometricPrecision"
			textRendering="optimizeLegibility"
			imageRendering="optimizeQuality"
			{...props}
		>
			<defs>
				{/* 3. Use unique IDs in definitions */}
				<linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
					<stop offset="0%" stopColor="#00D4FF" />
					<stop offset="100%" stopColor="#0066FF" />
				</linearGradient>
				<linearGradient id={pulseId} x1="0%" y1="0%" x2="100%" y2="0%">
					<stop offset="0%" stopColor="#00D4FF" stopOpacity="0" />
					<stop offset="50%" stopColor="#00D4FF" stopOpacity="0.8" />
					<stop offset="100%" stopColor="#00D4FF" stopOpacity="0" />
				</linearGradient>
				<filter id={glowId}>
					<feGaussianBlur stdDeviation="2.5" result="coloredBlur" />
					<feMerge>
						<feMergeNode in="coloredBlur" />
						<feMergeNode in="SourceGraphic" />
					</feMerge>
				</filter>
			</defs>

			{/* 4. Use unique IDs in references to definitions */}
			<g transform="translate(25, 25)">
				<circle
					cx="25"
					cy="25"
					r="24"
					fill="none"
					stroke={`url(#${gradientId})`}
					strokeWidth="2"
					opacity="0.8"
				/>
				<circle
					cx="25"
					cy="25"
					r="18"
					fill="none"
					stroke="#00D4FF"
					strokeWidth="1"
					opacity="0.5"
				/>
				<circle
					cx="25"
					cy="25"
					r="12"
					fill="none"
					stroke="#00D4FF"
					strokeWidth="1"
					opacity="0.4"
				/>
				<path
					d="M 25 25 L 40 15 M 25 25 L 40 35 M 25 25 L 10 15 M 25 25 L 10 35"
					stroke="#0066FF"
					strokeWidth="1"
					opacity="0.4"
				/>
				<circle
					cx="25"
					cy="25"
					r="8"
					fill={`url(#${gradientId})`}
					filter={`url(#${glowId})`}
				/>
				<circle cx="25" cy="25" r="4" fill="#FFFFFF" opacity="0.9" />
				<path
					d="M 25 5 L 25 10 M 25 40 L 25 45 M 5 25 L 10 25 M 40 25 L 45 25"
					stroke={`url(#${gradientId})`}
					strokeWidth="2"
					strokeLinecap="round"
				/>
				<path
					d="M 25 25 L 45 5"
					stroke={`url(#${pulseId})`}
					strokeWidth="2"
					opacity="0.7"
				>
					<animateTransform
						attributeName="transform"
						type="rotate"
						from="0 25 25"
						to="360 25 25"
						dur="4s"
						repeatCount="indefinite"
					/>
				</path>
			</g>

			{!iconOnly && (
				// --- Change fill from hardcoded color to a CSS variable ---
				<text
					x="110"
					y="54"
					dominantBaseline="middle"
					fontFamily="Montserrat, Helvetica, Arial, sans-serif"
					fontSize="38"
					fill="var(--logo-text-color, #FFFFFF)"
				>
					<tspan fontWeight="700">Depth</tspan>
					<tspan fill={`url(#${gradientId})`} fontWeight="300">
						Sight
					</tspan>
				</text>
			)}
		</svg>
	);
}
