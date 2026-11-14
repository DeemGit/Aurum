import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, updateSettings } from "@/api/settings";
import { setCurrency } from "@/lib/i18n";
import type { AppSettingsUpdate } from "@/types";

export function useAppSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
}

export function useUpdateAppSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AppSettingsUpdate) => updateSettings(input),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      setCurrency(data.currency);
      // Excluded tags affect dashboard aggregates and its transaction lists.
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}
