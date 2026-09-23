import { Button, Input, ScopeChip, cn } from "@iden/shared";
import { useMemo, useState } from "react";

export interface PickerOption {
  id: string;
  label: string;
  /** Rendered in the identity monospace — a scope value, a client id. */
  identifier?: string;
  hint?: string;
}

/**
 * A full-replace set editor.
 *
 * `PUT /admin/*` endpoints replace the whole set rather than diffing, so the UI
 * shows the resulting set the same way — a checklist, not an add/remove log.
 */
export function SetPicker({
  legend,
  options,
  selected,
  onChange,
  emptyLabel,
}: {
  legend: string;
  options: PickerOption[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  emptyLabel: string;
}) {
  const [filter, setFilter] = useState("");

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) =>
      `${option.label} ${option.identifier ?? ""}`.toLowerCase().includes(needle),
    );
  }, [options, filter]);

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
  }

  // Clipped: the rows are square and sit flush in the corners, so a hovered
  // first row would otherwise paint over the rounded border.
  return (
    <fieldset className="overflow-hidden rounded-lg border border-hairline">
      <legend className="sr-only">{legend}</legend>

      {options.length > 8 ? (
        <div className="border-b border-hairline p-3">
          <Input
            type="search"
            placeholder={`Filter ${legend.toLowerCase()}`}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
      ) : null}

      <div className="max-h-80 overflow-y-auto">
        {shown.length === 0 ? (
          <p className="p-5 text-body-sm text-muted-foreground">{emptyLabel}</p>
        ) : (
          shown.map((option) => (
            <label
              key={option.id}
              className={cn(
                "flex cursor-pointer items-start gap-3 border-b border-hairline-soft px-4 py-2.5 last:border-b-0",
                "hover:bg-row-hover",
              )}
            >
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 shrink-0 accent-primary"
                checked={selected.has(option.id)}
                onChange={() => toggle(option.id)}
              />
              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-2">
                  {option.identifier ? (
                    <ScopeChip value={option.identifier} />
                  ) : (
                    <span className="text-body-sm text-ink">{option.label}</span>
                  )}
                  {option.identifier ? (
                    <span className="text-body-sm text-body">{option.label}</span>
                  ) : null}
                </span>
                {option.hint ? (
                  <span className="mt-0.5 block text-caption text-muted-foreground">
                    {option.hint}
                  </span>
                ) : null}
              </span>
            </label>
          ))
        )}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-hairline px-4 py-2.5">
        <p className="text-caption text-muted-foreground" aria-live="polite">
          {selected.size} selected
        </p>
        <Button size="sm" variant="ghost" onClick={() => onChange(new Set())} type="button">
          Clear all
        </Button>
      </div>
    </fieldset>
  );
}
