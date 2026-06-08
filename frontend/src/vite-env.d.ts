/// <reference types="vite/client" />

interface ImportMetaEnv {
	readonly VITE_WS_URL: string;
	readonly VITE_API_BASE_URL: string;
	// other env variables...
}

interface ImportMeta {
	readonly env: ImportMetaEnv;
}
