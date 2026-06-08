// src/lib/queryKeys.ts

const hashString = (value: string): string => {
	let hash = 5381;
	for (let i = 0; i < value.length; i += 1) {
		hash = (hash * 33) ^ value.charCodeAt(i);
	}
	return (hash >>> 0).toString(36);
};

export const getAuthScope = (): string => {
	const token = localStorage.getItem("authToken");
	return token ? `auth:${hashString(token)}` : "auth:anonymous";
};

export const authScopedQueryKey = <T extends readonly unknown[]>(
	rootKey: string,
	...parts: T
) => [rootKey, getAuthScope(), ...parts] as const;
