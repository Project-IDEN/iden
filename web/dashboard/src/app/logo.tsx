import { AppLogo, Button, IdenError } from "@iden/shared";
import { ImageUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { problemWith, type LogoNotice } from "./logo-upload";

const HINT = "PNG, JPEG or WebP, up to 512 KB. Shown beside the name on the consent screen.";

const LOGO_FAILED =
  "The application was registered, but its logo could not be stored. Add it again here.";

function useFilePicker(onPick: (file: File) => void) {
  const input = useRef<HTMLInputElement>(null);
  return {
    open: () => input.current?.click(),
    element: (
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Cleared so choosing the same file again still fires a change.
          event.target.value = "";
          if (file) onPick(file);
        }}
      />
    ),
  };
}

/**
 * A logo chosen during registration. Nothing is uploaded here: the client does
 * not exist yet, so the file waits until it does.
 */
export function LogoPicker({
  name,
  file,
  onChange,
}: {
  name: string;
  file: File | null;
  onChange: (file: File | null) => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  const picker = useFilePicker((picked) => {
    const why = problemWith(picked);
    setProblem(why);
    if (!why) onChange(picked);
  });

  useEffect(() => () => (preview ? URL.revokeObjectURL(preview) : undefined), [preview]);

  return (
    <LogoRow
      name={name}
      src={preview}
      problem={problem}
      hint={HINT}
      actions={
        <>
          <Button type="button" size="sm" onClick={picker.open}>
            <ImageUp aria-hidden="true" />
            {file ? "Change logo" : "Add logo"}
          </Button>
          {file ? (
            <Button type="button" size="sm" variant="ghost" onClick={() => onChange(null)}>
              Remove
            </Button>
          ) : null}
        </>
      }
      input={picker.element}
    />
  );
}

/** A registered client's logo, uploaded or removed as soon as it is chosen. */
export function LogoControl({
  name,
  logoUrl,
  upload,
  remove,
}: {
  name: string;
  logoUrl: string | null;
  upload: { mutate: (file: File) => void; isPending: boolean; error: unknown };
  remove: { mutate: () => void; isPending: boolean };
}) {
  const notice = (useLocation().state as LogoNotice | null)?.logoFailed ? LOGO_FAILED : null;
  const [problem, setProblem] = useState<string | null>(null);
  const busy = upload.isPending || remove.isPending;
  const failure = upload.error instanceof IdenError ? upload.error.message : null;
  const picker = useFilePicker((file) => {
    const why = problemWith(file);
    setProblem(why);
    if (!why) upload.mutate(file);
  });

  return (
    <LogoRow
      name={name}
      src={logoUrl}
      problem={problem ?? failure ?? (logoUrl ? null : notice)}
      hint={busy ? "Working…" : HINT}
      actions={
        <>
          <Button type="button" size="sm" disabled={busy} onClick={picker.open}>
            <ImageUp aria-hidden="true" />
            {logoUrl ? "Change logo" : "Add logo"}
          </Button>
          {logoUrl ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => remove.mutate()}
            >
              Remove
            </Button>
          ) : null}
        </>
      }
      input={picker.element}
    />
  );
}

function LogoRow({
  name,
  src,
  problem,
  hint,
  actions,
  input,
}: {
  name: string;
  src: string | null;
  problem: string | null;
  hint: string;
  actions: ReactNode;
  input: ReactNode;
}) {
  return (
    <div className="flex items-center gap-5">
      <AppLogo name={name || "?"} src={src} size="lg" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
        <p
          role={problem ? "alert" : undefined}
          className={`mt-2 text-caption ${problem ? "text-destructive" : "text-muted-foreground"}`}
        >
          {problem ?? hint}
        </p>
        {input}
      </div>
    </div>
  );
}
