import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [react(), tailwindcss()],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "./src"),
		},
	},
	optimizeDeps: {
		include: [
			"@radix-ui/react-slider",
			"react-joyride",
			"react-resizable-panels",
		],
	},
	server: {
		host: "0.0.0.0", 
		port: 5173,
		proxy: {
			"/api": {
				target: "http://api:8000",
				changeOrigin: true,
				secure: false,
			},
			"/ws": {
				target: "http://api:8765",
				ws: true,
			},
			"/og-image": {
				target: "http://localhost:8000",
				changeOrigin: true,
			},
		},
	},
});
