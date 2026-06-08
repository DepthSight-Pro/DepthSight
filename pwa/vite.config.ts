import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// https://vitejs.dev/config/
export default defineConfig(({ command }) => {
	const isProduction = command === "build";

	return {
		plugins: [react(), tailwindcss()],

		// --- BASE PATH: CRITICALLY IMPORTANT FOR PRODUCTION ---
		// In production all assets will be at the path /pwa/, in development - in the root.
		base: isProduction ? "/pwa/" : "/",

		resolve: {
			alias: {
				"@": path.resolve(__dirname, "./src"),
				react: path.resolve(__dirname, "./node_modules/react"),
				"react-dom": path.resolve(__dirname, "./node_modules/react-dom"),
			},
		},

		server: {
			host: "0.0.0.0", // To access the dev server from Docker
			port: 5174,

			hmr: {
				host: "127.0.0.1",
				port: 5174,
			},
			proxy: {
				"/api/v1": {
					target: "http://api:8000", // Service name from docker-compose.yml (dev)
					changeOrigin: true,
					secure: false,
				},
				"/ws": {
					target: "ws://websocket:8765", // WebSocket service from docker-compose.yml
					ws: true,
					changeOrigin: true,
				},
			},
		},
	};
});
