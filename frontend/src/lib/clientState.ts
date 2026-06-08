// src/lib/clientState.ts

const USER_SCOPED_STORAGE_KEYS = [
	"ai-copilot-session-id",
	"depthsight-selected-account",
];

export const resetUserScopedClientState = () => {
	USER_SCOPED_STORAGE_KEYS.forEach((key) => {
		localStorage.removeItem(key);
	});
};
