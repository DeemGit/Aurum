import { cn } from "@/lib/utils";

interface DaySelectorProps {
  year: number;
  month: number; // 1–12
  selectedDays: number[];
  onChange: (days: number[]) => void;
}

function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

export function DaySelector({ year, month, selectedDays, onChange }: DaySelectorProps) {
  const count = daysInMonth(year, month);
  const selected = new Set(selectedDays);

  function toggleDay(day: number) {
    if (selected.has(day)) {
      onChange(selectedDays.filter((d) => d !== day).sort((a, b) => a - b));
    } else {
      onChange([...selectedDays, day].sort((a, b) => a - b));
    }
  }

  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:gap-2">
      {Array.from({ length: count }, (_, index) => {
        const day = index + 1;
        const active = selected.has(day);
        return (
          <button
            key={day}
            type="button"
            onClick={() => toggleDay(day)}
            className={cn(
              "shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium tabular-nums transition-colors sm:px-3 sm:py-1.5 sm:text-sm",
              active
                ? "border-series-6 bg-series-6 text-white"
                : "border-border bg-surface-1 text-text-secondary hover:bg-surface-2"
            )}
          >
            {day}
          </button>
        );
      })}
    </div>
  );
}
