// src/components/strategy-editor/JsonEditor.tsx

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";

export const JsonEditor = () => {
	const { t } = useTranslation("strategy-editor");
	const { toast } = useToast();
	const loadStrategy = useStrategyEditorStore((state) => state.loadStrategy);
	const jsonString = useStrategyEditorStore((state) =>
		JSON.stringify(state.toJson(), null, 2),
	);
	const [jsonText, setJsonText] = useState(jsonString);

	useEffect(() => {
		setJsonText(jsonString);
	}, [jsonString]);

	const handleApply = () => {
		try {
			loadStrategy(JSON.parse(jsonText));
			toast({
				title: t("jsonEditor.toastApplySuccessTitle"),
				description: t("jsonEditor.toastApplySuccess"),
			});
		} catch (error) {
			toast({
				variant: "destructive",
				title: t("jsonEditor.toastParseError"),
				description: (error as Error).message,
			});
		}
	};

	return (
		<div className="h-full flex flex-col p-4">
			<h3 className="text-lg font-semibold mb-2">{t("jsonEditor.title")}</h3>
			<p className="text-sm text-muted-foreground mb-4">
				{t("jsonEditor.description")}
			</p>
			<Textarea
				value={jsonText}
				onChange={(e) => setJsonText(e.target.value)}
				className="flex-grow font-mono text-xs"
				placeholder={t("jsonEditor.placeholder")}
			/>
			<div className="flex justify-end mt-4">
				<Button onClick={handleApply}>{t("jsonEditor.applyButton")}</Button>
			</div>
		</div>
	);
};
