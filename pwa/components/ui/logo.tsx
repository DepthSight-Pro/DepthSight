// pwa/components/ui/logo.tsx

import type React from "react";

// Defining possible sizes
type LogoSize = "sm" | "md" | "lg" | "xl" | "full";

// Defining component props
interface LogoProps extends React.SVGProps<SVGSVGElement> {
	size?: LogoSize;
	className?: string;
}

// Size map
const sizeClasses: Record<LogoSize, string> = {
	sm: "h-8",
	md: "h-10",
	lg: "h-16",
	xl: "h-20",
	full: "w-full h-auto",
};

export const Logo: React.FC<LogoProps> = ({
	size = "md",
	className,
	...props
}) => {
	const logoSizeClass = sizeClasses[size];

	// Simple string concatenation instead of the cn utility
	const finalClassName = `w-auto ${logoSizeClass} ${className || ""}`.trim();

	return (
		<svg
			viewBox="0 0 320 100"
			xmlns="http://www.w3.org/2000/svg"
			shapeRendering="geometricPrecision"
			textRendering="optimizeLegibility"
			imageRendering="optimizeQuality"
			className={finalClassName} // Using our joined string
			{...props}
		>
			<style>
				{`
          .logo-text-depth { fill: #FFFFFF !important; }
          @keyframes logo-rotate-spinner {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
          .logo-spinner-path {
            transform-origin: 25px 25px;
            animation: logo-rotate-spinner 4s linear infinite;
          }
        `}
			</style>
			<defs>
				<linearGradient
					id="dashLogoTechGradient"
					x1="0%"
					y1="0%"
					x2="100%"
					y2="100%"
				>
					<stop offset="0%" stopColor="#00D4FF"></stop>
					<stop offset="100%" stopColor="#0066FF"></stop>
				</linearGradient>
				<linearGradient
					id="dashLogoPulseGradient"
					x1="0%"
					y1="0%"
					x2="100%"
					y2="0%"
				>
					<stop offset="0%" stopColor="#00D4FF" stopOpacity="0"></stop>
					<stop offset="50%" stopColor="#00D4FF" stopOpacity="0.8"></stop>
					<stop offset="100%" stopColor="#00D4FF" stopOpacity="0"></stop>
				</linearGradient>
				<filter id="dashLogoGlow">
					<feGaussianBlur
						stdDeviation="2.5"
						result="coloredBlur"
					></feGaussianBlur>
					<feMerge>
						<feMergeNode in="coloredBlur"></feMergeNode>
						<feMergeNode in="SourceGraphic"></feMergeNode>
					</feMerge>
				</filter>
			</defs>
			<g transform="translate(25, 25)">
				<circle
					cx="25"
					cy="25"
					r="24"
					fill="none"
					stroke="url(#dashLogoTechGradient)"
					strokeWidth="2"
					opacity="0.8"
				></circle>
				<circle
					cx="25"
					cy="25"
					r="18"
					fill="none"
					stroke="#00D4FF"
					strokeWidth="1"
					opacity="0.5"
				></circle>
				<circle
					cx="25"
					cy="25"
					r="12"
					fill="none"
					stroke="#00D4FF"
					strokeWidth="1"
					opacity="0.4"
				></circle>
				<path
					d="M 25 25 L 40 15 M 25 25 L 40 35 M 25 25 L 10 15 M 25 25 L 10 35"
					stroke="#0066FF"
					strokeWidth="1"
					opacity="0.4"
				></path>
				<circle
					cx="25"
					cy="25"
					r="8"
					fill="url(#dashLogoTechGradient)"
					filter="url(#dashLogoGlow)"
				></circle>
				<circle cx="25" cy="25" r="4" fill="#FFFFFF" opacity="0.9"></circle>
				<path
					d="M 25 5 L 25 10 M 25 40 L 25 45 M 5 25 L 10 25 M 40 25 L 45 25"
					stroke="url(#dashLogoTechGradient)"
					strokeWidth="2"
					strokeLinecap="round"
				></path>
				<path
					className="logo-spinner-path"
					d="M 25 25 L 45 5"
					stroke="url(#dashLogoPulseGradient)"
					strokeWidth="2"
					opacity="0.7"
				></path>
			</g>
			<text
				x="110"
				y="54"
				dominant-baseline="middle"
				fontFamily="Montserrat, Helvetica, Arial, sans-serif"
				fontSize="38"
			>
				<tspan fontWeight="700" className="logo-text-depth">
					Depth
				</tspan>
				<tspan
					fill="url(#dashLogoTechGradient)"
					fontWeight="300"
					className="logo-text-sight"
				>
					Sight
				</tspan>
			</text>
		</svg>
	);
};
