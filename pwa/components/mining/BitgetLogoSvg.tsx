import React from "react";

export const BitgetLogoSvg: React.FC<{ className?: string }> = ({ className = "w-full h-full" }) => (
	<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2500 2500" className={className}>
		<circle fill="#1DA2B4" cx="1250" cy="1250" r="1250" />
		<g fill="#FFFFFF" fillRule="evenodd" clipRule="evenodd">
			<path d="M925,415c22-24,54-37,86-37h212c27,0,41,32,22,51L826,876h231l235,249H826l466,499h-282c-33,0-64-14-86-37 l-473-506c-42-45-42-115,0-160l473-506H925z" />
			<path d="M1575,2085c-22,24-54,37-86,37h-212c-27,0-41-32-22-51l419-447h-231l-235-249h466l-466-499h282 c33,0,64,14,86,37l473,506c42,45,42,115,0,160l-473,506H1575z" />
		</g>
	</svg>
);
