import { api } from "@/api/client";
import type { AppSettings, AppSettingsUpdate } from "@/types";

export function fetchSettings() {
  return api.get<AppSettings>("/settings");
}

// Partial — the backend applies whatever fields are present (PATCH
// semantics), so callers only send the field(s) they're changing.
export function updateSettings(input: AppSettingsUpdate) {
  return api.patch<AppSettings>("/settings", input);
}
