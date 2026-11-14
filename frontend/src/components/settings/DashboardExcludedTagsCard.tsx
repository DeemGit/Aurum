import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { TagInput } from "@/components/transactions/TagInput";
import { useAppSettings, useUpdateAppSettings } from "@/hooks/useSettings";
import { useTranslation } from "@/lib/i18n";
import type { Tag } from "@/types";

export function DashboardExcludedTagsCard() {
  const { t } = useTranslation();
  const { data: settings } = useAppSettings();
  const updateSettings = useUpdateAppSettings();
  const [selected, setSelected] = useState<Tag[]>([]);

  useEffect(() => {
    if (!settings) return;
    setSelected(settings.dashboard_excluded_tags ?? []);
  }, [settings]);

  function handleChange(tags: Tag[]) {
    setSelected(tags);
    const nextIds = tags.map((tag) => tag.id).sort((a, b) => a - b);
    const prevIds = (settings?.dashboard_excluded_tags ?? []).map((tag) => tag.id).sort((a, b) => a - b);
    if (nextIds.length === prevIds.length && nextIds.every((id, index) => id === prevIds[index])) {
      return;
    }
    updateSettings.mutate({ dashboard_excluded_tag_ids: nextIds });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.excludedTagsTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <TagInput value={selected} onChange={handleChange} />
        <p className="text-xs text-text-muted">{t("settings.excludedTagsHint")}</p>
      </CardContent>
    </Card>
  );
}
