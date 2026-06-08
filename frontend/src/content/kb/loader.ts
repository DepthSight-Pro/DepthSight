// src/content/kb/loader.ts

const ruArticles = import.meta.glob("./ru/*.md", {
	query: "?raw",
	import: "default",
});
const enArticles = import.meta.glob("./en/*.md", {
	query: "?raw",
	import: "default",
});

export const getArticleContent = async (
	lang: string,
	id: string,
): Promise<string> => {
	const articles = lang.startsWith("ru") ? ruArticles : enArticles;
	const path = `./${lang.startsWith("ru") ? "ru" : "en"}/${id}.md`;

	const loader = articles[path];
	if (loader) {
		return (await loader()) as string;
	}

	throw new Error(`Article ${id} not found for language ${lang}`);
};
