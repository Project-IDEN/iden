import type { IdenError } from "@iden/shared";
import { Button, Row } from "@iden/shared";
import type { ReactNode } from "react";
import { useStepUp } from "../../app/session";

/**
 * One thing about how you sign in: what is true now on the left, the way to
 * change it on the right, and the form only once you have asked for it.
 *
 * The page used to be three forms open at once, which made it about filling
 * them in. It is read far more often than it is used — the question people
 * arrive with is "is my authenticator on?", not "what is my new password?" —
 * so the answers come first and the forms come on request.
 */
export function Setting({
  title,
  status,
  action,
  children,
}: {
  title: string;
  status: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Row className="px-6 py-5">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h2 className="text-title-sm text-ink">{title}</h2>
          <div aria-live="polite" className="mt-1 text-body-sm text-muted-foreground">
            {status}
          </div>
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
      {children ? <div className="mt-6 max-w-md">{children}</div> : null}
    </Row>
  );
}

/** A setting whose status has not loaded yet, or failed to. */
export function PendingSetting({
  title,
  failed,
  failure,
  onRetry,
}: {
  title: string;
  failed: boolean;
  failure: string;
  onRetry: () => void;
}) {
  return (
    <Setting
      title={title}
      status={failed ? failure : "Checking…"}
      action={
        failed ? (
          <Button size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : null
      }
    />
  );
}

/**
 * Both credential changes require a sign-in within the last five minutes. When
 * the server says so (RFC 9470), the fix is to re-authenticate and come back —
 * not to show the user an error they cannot act on.
 */
export function StepUpNotice({ problem }: { problem: IdenError | null }) {
  const stepUp = useStepUp();
  const maxAge = problem?.stepUpMaxAge;
  if (!maxAge) return null;

  return (
    <div className="rounded-lg border border-hairline bg-surface-soft p-5">
      <p className="text-title-sm text-ink">Confirm it's you first</p>
      <p className="mt-1 text-body-sm text-body">
        Changing this needs a sign-in from the last {Math.round(maxAge / 60)} minutes.
      </p>
      <Button className="mt-4" size="sm" variant="default" onClick={() => stepUp(maxAge)}>
        Enter your password
      </Button>
    </div>
  );
}

/** A refused change: the way to step up when that is the fix, the message otherwise. */
export function Problem({ problem }: { problem: IdenError | null }) {
  if (!problem) return null;
  if (problem.stepUpMaxAge) return <StepUpNotice problem={problem} />;
  return (
    <p role="alert" className="text-body-sm text-error">
      {problem.message}
    </p>
  );
}
