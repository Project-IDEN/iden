import { AppWindow, Check, Copy, KeyRound, TriangleAlert, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "./alert-dialog";
import { Badge } from "./badge";
import { Button } from "./button";

/**
 * Names what will happen before it happens, including the consequences the
 * server would otherwise deliver as a surprise — a `force=true` delete taking
 * dependants with it, a password reset ending every session.
 *
 * An `AlertDialog` rather than a `Dialog`: this interrupts to ask a question
 * whose answer cannot be undone, so it takes focus, traps escape to Cancel, and
 * is announced as an alert.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  onConfirm,
  destructive = true,
  pending = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  destructive?: boolean;
  pending?: boolean;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        {destructive ? (
          <span
            aria-hidden="true"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10 text-destructive"
          >
            <TriangleAlert className="h-5 w-5" />
          </span>
        ) : null}
        <AlertDialogTitle className="font-display text-display-sm text-foreground">
          {title}
        </AlertDialogTitle>
        <AlertDialogDescription asChild>
          <div className="text-body-md text-body">{body}</div>
        </AlertDialogDescription>
        <AlertDialogFooter>
          <AlertDialogCancel variant="outline" size="default">
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            variant={destructive ? "destructive" : "default"}
            size="default"
            disabled={pending}
            // Radix closes the dialog on action. The work that follows is the
            // caller's, and some of it reopens this — so the close is left to
            // the caller's state rather than taken here.
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/**
 * Client secrets and generated passwords are returned exactly once and never
 * stored. The screen has to say so before it is dismissed, not after.
 */
export function SecretRevealOnce({
  label,
  secret,
  note,
}: {
  label: string;
  secret: string;
  note?: string;
}) {
  return (
    <RevealCard
      icon={KeyRound}
      label={label}
      value={secret}
      badge="Shown once"
      note={
        note ?? "This is the only time it is shown. Store it now — it cannot be retrieved later."
      }
    />
  );
}

/**
 * A value worth copying that is **not** secret — a client ID beside the secret
 * it came with. Same card, so the two read as one handover, but without the
 * "shown once" warning: an identifier that is always on the record's own page
 * must not be presented as something about to be lost.
 */
export function CopyableValue({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return <RevealCard icon={AppWindow} label={label} value={value} note={note} />;
}

function RevealCard({
  icon: Icon,
  label,
  value,
  badge,
  note,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  badge?: string;
  note?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="rounded-lg bg-surface-dark p-6">
      <div className="flex items-center justify-between gap-4">
        <p className="flex items-center gap-2 text-caption-upper uppercase text-on-dark-soft">
          <Icon aria-hidden="true" className="h-3.5 w-3.5 text-primary" />
          {label}
        </p>
        {badge ? <Badge>{badge}</Badge> : null}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <code className="font-identity min-w-0 flex-1 break-all text-on-dark">{value}</code>
        <Button variant="onDark" size="sm" onClick={copy}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      {note ? <p className="mt-4 text-body-sm text-on-dark-soft">{note}</p> : null}
      <span aria-live="polite" className="sr-only">
        {copied ? `${label} copied to clipboard` : ""}
      </span>
    </div>
  );
}
