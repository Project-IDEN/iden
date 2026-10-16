import { CircleAlert, Inbox, Info, RotateCw, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";
import { IdenError } from "../api/errors";
import { Alert, AlertDescription, AlertTitle } from "./alert";
import { Button } from "./button";

/**
 * The three states a screen can be in besides "here is the data". None has a
 * shadcn equivalent — they are compositions of one, and what makes them worth
 * having is the wording rather than the markup.
 */

/**
 * An empty list is an invitation to act, never "No data". The caller supplies
 * the action, because what to do next depends on what is empty.
 */
export function EmptyState({
  title,
  body,
  action,
  icon: Icon = Inbox,
}: {
  title: string;
  body: string;
  action?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-secondary/40 px-8 py-14 text-center">
      <span
        aria-hidden="true"
        className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-surface-card text-muted-foreground"
      >
        <Icon className="h-5 w-5" />
      </span>
      <p className="mt-5 font-display text-display-sm text-foreground">{title}</p>
      <p className="mx-auto mt-2 max-w-prose text-body-sm text-body">{body}</p>
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  );
}

/**
 * Errors say what happened and what to do. The rate-limit and outage cases get
 * their own wording because "something went wrong" is wrong for both — the user
 * did nothing wrong, and waiting is the fix.
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const problem = error instanceof IdenError ? error : null;
  const wait = problem?.retryAfter;

  const message =
    problem?.status === 429
      ? `Too many attempts. Try again in ${wait ?? 60} seconds.`
      : problem?.status === 503
        ? "The server is not accepting requests right now. This is usually brief."
        : (problem?.message ?? "Something went wrong.");

  return (
    <Alert className="bg-secondary">
      <TriangleAlert aria-hidden="true" className="text-destructive" />
      <AlertTitle className="text-title-sm text-foreground">{message}</AlertTitle>
      <AlertDescription>
        {problem?.code && problem.status !== 429 ? (
          <span className="font-identity text-caption text-muted-foreground">{problem.code}</span>
        ) : null}
        {onRetry ? (
          <Button className="mt-3" size="sm" onClick={onRetry}>
            <RotateCw aria-hidden="true" />
            Try again
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

const NOTICE_TONES = {
  // The person can fix it: a wrong password, a code that did not match.
  error: { box: "border-error/25 bg-error/[0.06]", icon: "text-error", Icon: CircleAlert },
  // Nothing they did, and nothing lost: bad light, a busy service.
  caution: {
    box: "border-accent-amber/45 bg-accent-amber/10",
    icon: "text-warning",
    Icon: TriangleAlert,
  },
  // Not a failure at all, only what happens next: wait, or start again.
  info: { box: "border-hairline bg-surface-soft", icon: "text-muted-foreground", Icon: Info },
} as const;

/**
 * A message beside a form: what happened, in a title a glance can read, and
 * what to do about it beneath. The tone says whose problem it is, so a rate
 * limit never looks like the person's mistake.
 */
export function Notice({
  tone = "error",
  title,
  children,
}: {
  tone?: keyof typeof NOTICE_TONES;
  title: ReactNode;
  children?: ReactNode;
}) {
  const { box, icon, Icon } = NOTICE_TONES[tone];
  return (
    <div role="alert" className={cn("flex gap-3 rounded-lg border px-4 py-3", box)}>
      <Icon aria-hidden="true" className={cn("mt-0.5 h-4 w-4 shrink-0", icon)} />
      <div className="min-w-0">
        <p className="text-body-sm font-medium text-ink">{title}</p>
        {children ? <div className="mt-1 text-body-sm text-body">{children}</div> : null}
      </div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-body-sm text-muted-foreground" role="status">
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-primary"
      />
      {label}
    </div>
  );
}
