import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
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

function rangeDays(start: number, end: number): number[] {
  const lo = Math.min(start, end);
  const hi = Math.max(start, end);
  const days: number[] = [];
  for (let d = lo; d <= hi; d += 1) days.push(d);
  return days;
}

export function DaySelector({ year, month, selectedDays, onChange }: DaySelectorProps) {
  const count = daysInMonth(year, month);
  const selected = new Set(selectedDays);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);
  const suppressClickRef = useRef(false);
  const didDragRef = useRef(false);

  const preview =
    dragStart != null && dragEnd != null ? new Set(rangeDays(dragStart, dragEnd)) : null;

  function toggleDay(day: number) {
    if (selected.has(day)) {
      onChange(selectedDays.filter((d) => d !== day).sort((a, b) => a - b));
    } else {
      onChange([...selectedDays, day].sort((a, b) => a - b));
    }
  }

  function commitRange(start: number, end: number) {
    const days = rangeDays(start, end);
    const allSelected = days.every((d) => selected.has(d));
    if (allSelected) {
      const drop = new Set(days);
      onChange(selectedDays.filter((d) => !drop.has(d)).sort((a, b) => a - b));
    } else {
      const next = new Set(selectedDays);
      for (const d of days) next.add(d);
      onChange([...next].sort((a, b) => a - b));
    }
  }

  function dayFromPoint(clientX: number, clientY: number): number | null {
    const el = document.elementFromPoint(clientX, clientY);
    if (!(el instanceof HTMLElement)) return null;
    const chip = el.closest("[data-day]");
    if (!(chip instanceof HTMLElement)) return null;
    const day = Number(chip.dataset.day);
    return Number.isInteger(day) && day >= 1 && day <= count ? day : null;
  }

  function handlePointerDown(day: number, event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    didDragRef.current = false;
    suppressClickRef.current = false;
    setDragStart(day);
    setDragEnd(day);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    if (dragStart == null) return;
    const day = dayFromPoint(event.clientX, event.clientY);
    if (day == null) return;
    if (day !== dragEnd) {
      didDragRef.current = true;
      setDragEnd(day);
    }
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    if (dragStart == null) return;
    const end = dragEnd ?? dragStart;
    if (didDragRef.current && end !== dragStart) {
      commitRange(dragStart, end);
      suppressClickRef.current = true;
    }
    setDragStart(null);
    setDragEnd(null);
    didDragRef.current = false;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Already released.
    }
  }

  function handleClick(day: number) {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    toggleDay(day);
  }

  return (
    <div
      className={cn(
        "flex gap-1.5 overflow-x-auto pb-1 select-none [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        dragStart != null && "touch-none"
      )}
    >
      {Array.from({ length: count }, (_, index) => {
        const day = index + 1;
        const inPreview = preview?.has(day) ?? false;
        const active = selected.has(day) || inPreview;
        return (
          <button
            key={day}
            type="button"
            data-day={day}
            onClick={() => handleClick(day)}
            onPointerDown={(event) => handlePointerDown(day, event)}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            className={cn(
              "shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium tabular-nums transition-colors sm:px-3 sm:py-1.5 sm:text-sm",
              active
                ? inPreview && !selected.has(day)
                  ? "border-series-6/70 bg-series-6/70 text-white"
                  : "border-series-6 bg-series-6 text-white"
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
