import { Switch } from "@iden/shared";

/** A switch with its label beside it and what turning it on means beneath. */
export function SwitchRow({
  id,
  checked,
  onChange,
  label,
  hint,
}: {
  id: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <div className="flex items-start gap-4">
      <Switch id={id} checked={checked} onCheckedChange={onChange} className="mt-1" />
      <div className="min-w-0">
        <label htmlFor={id} className="text-body-sm text-foreground">
          {label}
        </label>
        {hint ? <p className="mt-1 text-caption text-muted-foreground">{hint}</p> : null}
      </div>
    </div>
  );
}
