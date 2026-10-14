import { Badge, cn } from "@iden/shared";
import { Check } from "lucide-react";
import { BLANK_KEY, type Preset } from "./profile-field-form";

/**
 * The catalogue, grouped the way the server groups it.
 *
 * Each card leads with `rationale` rather than the field's own description: the
 * reader here is an administrator deciding whether they want the field, not the
 * person who will eventually fill it in.
 *
 * Picking one moves the flow on. The choice *is* the answer to this step, so a
 * second click on Continue would carry no information — but the selection is
 * still marked, because the step can be returned to from the stepper.
 */
export function PresetPicker({
  presets,
  chosen,
  onPick,
  onBlank,
}: {
  presets: Preset[];
  chosen: string | null;
  onPick: (preset: Preset) => void;
  onBlank: () => void;
}) {
  const categories = [...new Set(presets.map((preset) => preset.category))];

  return (
    <div className="flex flex-col gap-8">
      <button
        type="button"
        onClick={onBlank}
        aria-pressed={chosen === BLANK_KEY}
        className={cn(
          "rounded-lg border border-dashed px-5 py-4 text-left transition-colors duration-100",
          chosen === BLANK_KEY
            ? "border-primary bg-secondary/60"
            : "border-border hover:bg-secondary/40",
        )}
      >
        <p className="text-title-sm text-foreground">Start from nothing</p>
        <p className="mt-1 text-body-sm text-muted-foreground">Define every part yourself.</p>
      </button>

      {categories.map((category) => (
        <section key={category}>
          <h3 className="mb-3 text-caption-upper uppercase text-muted-foreground">{category}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {presets
              .filter((preset) => preset.category === category)
              .map((preset) => (
                <PresetCard
                  key={preset.key}
                  preset={preset}
                  selected={chosen === preset.key}
                  onPick={() => onPick(preset)}
                />
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function PresetCard({
  preset,
  selected,
  onPick,
}: {
  preset: Preset;
  selected: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={selected}
      className={cn(
        "relative rounded-lg border px-4 py-3.5 text-left transition-colors duration-100",
        selected
          ? "border-primary bg-secondary/60"
          : "border-border hover:border-primary hover:bg-secondary/40",
      )}
    >
      {selected ? (
        <Check aria-hidden="true" className="absolute right-3 top-3.5 h-4 w-4 text-primary" />
      ) : null}
      <span className="flex flex-wrap items-center gap-2 pr-6">
        <span className="text-title-sm text-foreground">{preset.label}</span>
        <Badge variant="secondary">{preset.dataType}</Badge>
        {preset.userWritable ? null : <Badge variant="outline">org-owned</Badge>}
      </span>
      <span className="mt-1.5 block text-body-sm text-muted-foreground">{preset.rationale}</span>
    </button>
  );
}
