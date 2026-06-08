import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

// Placeholder for other PWA specific translations
import pwaCommonEn from "./locales/en/pwa-common.json";
import pwaCommonRu from "./locales/ru/pwa-common.json";

const resources = {
	en: {
		"pwa-common": { ...pwaCommonEn },
		// Add other PWA specific namespaces here
	},
	ru: {
		"pwa-common": { ...pwaCommonRu },
		// Add other PWA specific namespaces here
	},
};

i18n
	.use(LanguageDetector)
	.use(initReactI18next)
	.init({
		resources,
		fallbackLng: "en",
		supportedLngs: ["en", "ru"],
		debug: import.meta.env.DEV,
		defaultNS: "pwa-common",
		interpolation: {
			escapeValue: false,
		},
	});

export default i18n;
