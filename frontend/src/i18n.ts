import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import accountEn from "./locales/en/account.json";
import achievementsEn from "./locales/en/achievements.json";
import affiliateEn from "./locales/en/affiliate.json";
import analyticsEn from "./locales/en/analytics.json";
// Import all translation files directly
import commonEn from "./locales/en/common.json";
import communityEn from "./locales/en/community.json";
import confirmEmailEn from "./locales/en/confirmEmail.json";
import diagnosticsEn from "./locales/en/diagnostics.json";
import discoveryEn from "./locales/en/discovery.json";
import eventLogEn from "./locales/en/eventLog.json";
import indexEn from "./locales/en/index.json";
import laboratoryEn from "./locales/en/LaboratoryPage.json";
import leaderboardEn from "./locales/en/leaderboard.json";
import loginEn from "./locales/en/login.json";
import modelLabEn from "./locales/en/modelLab.json";
import navigationEn from "./locales/en/navigation.json";
import notFoundEn from "./locales/en/notFound.json";
import positionsEn from "./locales/en/positions.json";
import registerEn from "./locales/en/register.json";
import researchEn from "./locales/en/research.json";
import settingsEn from "./locales/en/settings.json";
import simulationEn from "./locales/en/simulation.json";
import strategiesEn from "./locales/en/strategies.json";
import strategyEditorEn from "./locales/en/strategy-editor.json";
import supportEn from "./locales/en/support.json";
import accountRu from "./locales/ru/account.json";
import achievementsRu from "./locales/ru/achievements.json";
import affiliateRu from "./locales/ru/affiliate.json";
import analyticsRu from "./locales/ru/analytics.json";
import commonRu from "./locales/ru/common.json";
import communityRu from "./locales/ru/community.json";
import confirmEmailRu from "./locales/ru/confirmEmail.json";
import diagnosticsRu from "./locales/ru/diagnostics.json";
import discoveryRu from "./locales/ru/discovery.json";
import eventLogRu from "./locales/ru/eventLog.json";
import indexRu from "./locales/ru/index.json";
import laboratoryRu from "./locales/ru/LaboratoryPage.json";
import leaderboardRu from "./locales/ru/leaderboard.json";
import loginRu from "./locales/ru/login.json";
import modelLabRu from "./locales/ru/modelLab.json";
import navigationRu from "./locales/ru/navigation.json";
import notFoundRu from "./locales/ru/notFound.json";
import positionsRu from "./locales/ru/positions.json";
import registerRu from "./locales/ru/register.json";
import researchRu from "./locales/ru/research.json";
import settingsRu from "./locales/ru/settings.json";
import simulationRu from "./locales/ru/simulation.json";
import strategiesRu from "./locales/ru/strategies.json";
import strategyEditorRu from "./locales/ru/strategy-editor.json";
import supportRu from "./locales/ru/support.json";

const resources = {
	en: {
		common: commonEn,
		analytics: analyticsEn,
		discovery: discoveryEn,
		eventLog: eventLogEn,
		index: indexEn,
		login: loginEn,
		navigation: navigationEn,
		notFound: notFoundEn,
		positions: positionsEn,
		research: researchEn,
		settings: settingsEn,
		strategies: strategiesEn,
		"strategy-editor": { ...strategyEditorEn },
		modelLab: modelLabEn,
		diagnostics: diagnosticsEn,
		account: accountEn,
		register: registerEn,
		affiliate: affiliateEn,
		achievements: achievementsEn,
		leaderboard: leaderboardEn,
		laboratory: laboratoryEn,
		confirmEmail: confirmEmailEn,
		simulation: simulationEn,
		support: supportEn,
		community: communityEn,
	},
	ru: {
		common: commonRu,
		analytics: analyticsRu,
		discovery: discoveryRu,
		eventLog: eventLogRu,
		index: indexRu,
		login: loginRu,
		navigation: navigationRu,
		notFound: notFoundRu,
		positions: positionsRu,
		research: researchRu,
		settings: settingsRu,
		strategies: strategiesRu,
		"strategy-editor": { ...strategyEditorRu },
		modelLab: modelLabRu,
		diagnostics: diagnosticsRu,
		account: accountRu,
		register: registerRu,
		affiliate: affiliateRu,
		achievements: achievementsRu,
		leaderboard: leaderboardRu,
		laboratory: laboratoryRu,
		confirmEmail: confirmEmailRu,
		simulation: simulationRu,
		support: supportRu,
		community: communityRu,
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
		defaultNS: "common",
		interpolation: {
			escapeValue: false,
		},
	});

export default i18n;
