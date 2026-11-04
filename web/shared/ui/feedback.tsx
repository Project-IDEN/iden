import { CircleAlert, Inbox, Info, RotateCw, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";
import { IdenError } from "../api/errors";
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
 * Errors say what happened and what to do. The rate-limit, outage and offline
 * cases get their own wording and the caution tone because "something went
 * wrong" is wrong for all three — the person did nothing wrong, and waiting is
 * the fix. It is a `Notice`, so a failed load looks like a failed sign-in.
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const problem = error instanceof IdenError ? error : null;
  const status = problem?.status;
  const offline = problem?.code === "network_error";

  const title =
    status === 429
      ? "Too many attempts"
      : status === 503
        ? "The server is busy"
        : offline
          ? "Could not reach the server"
          : (problem?.message ?? "Something went wrong");

  const hint =
    status === 429
      ? `Try again in ${problem?.retryAfter ?? 60} seconds.`
      : status === 503
        ? "It is not accepting requests right now. This is usually brief."
        : offline
          ? "Check your connection and try again."
          : null;

  return (
    <Notice tone={status === 429 || status === 503 || offline ? "caution" : "error"} title={title}>
      {hint ? <p>{hint}</p> : null}
      {onRetry ? (
        <Button className={hint ? "mt-3" : "mt-1"} variant="outline" size="sm" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          Try again
        </Button>
      ) : null}
    </Notice>
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
