// pwa/components/FAB.tsx

import type React from "react";

interface FABProps {
	onClick: () => void;
}

const FAB: React.FC<FABProps> = ({ onClick }) => {
	return (
		<button
			type="button"
			onClick={onClick}
			className="fixed bottom-[90px] right-5 w-14 h-14 rounded-2xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-none shadow-lg cursor-pointer flex items-center justify-center text-2xl transition-all duration-300 z-10 hover:scale-110 hover:shadow-xl"
			aria-label="Add"
		>
			+
		</button>
	);
};

export default FAB;
