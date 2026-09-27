import {
  Button,
  ConfirmDialog,
  Field,
  IdenError,
  Input,
  Row,
  RowCard,
  SecretRevealOnce,
  StatusDot,
} from "@iden/shared";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useState, type ReactNode } from "react";
import { useApi } from "../../app/api";
import { useStepUp } from "../../app/session";
import { PageHeader } from "../../app/shell";
import { useProfile, useTotpStatus, type TotpEnrollment, type TotpStatus } from "./api";

export function SecurityRoute() {
  return (
    <>
      <PageHeader
        title="Security"
        lede="Your password, the address you sign in with, and your authenticator app."
      />
      <RowCard className="max-w-3xl">
        <PasswordSetting />
        <EmailSetting />
        <TotpSetting />
      </RowCard>
    </>
  );
}

/**
 * One thing about how you sign in: what is true now on the left, the way to
 * change it on the right, and the form only once you have asked for it.
 *
 * The page used to be three forms open at once, which made it about filling
 * them in. It is read far more often than it is used — the question people
 * arrive with is "is my authenticator on?", not "what is my new password?" —
 * so the answers come first and the forms come on request.
 */
function Setting({
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

/** The open/close button every setting shares. */
function Toggle({ open, onOpenChange, label }: OpenState & { label: string }) {
  return (
    <Button size="sm" variant={open ? "ghost" : "outline"} onClick={() => onOpenChange(!open)}>
      {open ? "Cancel" : label}
    </Button>
  );
}

interface OpenState {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Both credential changes require a sign-in within the last five minutes. When
 * the server says so (RFC 9470), the fix is to re-authenticate and come back —
 * not to show the user an error they cannot act on.
 */
function StepUpNotice({ problem }: { problem: IdenError | null }) {
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

function PasswordSetting() {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [currentPassword, setCurrent] = useState("");
  const [newPassword, setNext] = useState("");

  const change = useMutation({
    mutationFn: async () => {
      const response = await api.post<{ sessionsEnded: number }>("/entity/credentials/password", {
        currentPassword,
        newPassword,
      });
      return response.data;
    },
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setOpen(false);
    },
  });

  const problem = change.error instanceof IdenError ? change.error : null;
  const ended = change.data?.sessionsEnded ?? 0;

  return (
    <Setting
      title="Password"
      status={
        change.isSuccess && !open
          ? `Changed. ${ended} other session${ended === 1 ? "" : "s"} signed out.`
          : "Changing it signs out every other session you have open."
      }
      action={<Toggle open={open} onOpenChange={setOpen} label="Change password" />}
    >
      {open ? (
        <form
          noValidate
          className="flex flex-col gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            change.mutate();
          }}
        >
          <Field label="Current password">
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrent(event.target.value)}
              />
            )}
          </Field>
          <Field
            label="New password"
            hint="At least 12 characters."
            error={
              problem?.code === "same_password"
                ? "Choose a password you haven't used here."
                : undefined
            }
          >
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNext(event.target.value)}
              />
            )}
          </Field>

          <StepUpNotice problem={problem} />

          {problem && !problem.stepUpMaxAge && problem.code !== "same_password" ? (
            <p role="alert" className="text-body-sm text-error">
              {problem.code === "wrong_password"
                ? "That current password is not right."
                : problem.message}
            </p>
          ) : null}

          <Button
            type="submit"
            variant="default"
            className="self-start"
            disabled={change.isPending}
          >
            {change.isPending ? "Changing…" : "Change password"}
          </Button>
        </form>
      ) : null}
    </Setting>
  );
}

function EmailSetting() {
  const api = useApi();
  const profile = useProfile(api);

  return (
    <Setting
      title="Sign-in address"
      status={
        profile.data ? (
          <>
            You sign in as <span className="text-body-strong">{profile.data.email}</span>. It was
            given to you by your organization and cannot be changed.
          </>
        ) : (
          "The address you sign in with."
        )
      }
    />
  );
}

function TotpSetting() {
  const api = useApi();
  const status = useTotpStatus(api);
  const queryClient = useQueryClient();
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null);
  const [code, setCode] = useState("");
  const [removing, setRemoving] = useState(false);

  const enroll = useMutation({
    mutationFn: async () => {
      const response = await api.post<TotpEnrollment>("/entity/totp/enroll");
      return response.data;
    },
    onSuccess: setEnrollment,
  });

  const confirm = useMutation({
    mutationFn: async () => {
      const response = await api.post<TotpStatus>("/entity/totp/confirm", { code });
      return response.data;
    },
    onSuccess: (next) => {
      queryClient.setQueryData(["totp"], next);
      setEnrollment(null);
      setCode("");
    },
  });

  const remove = useMutation({
    mutationFn: () => api.delete("/entity/totp"),
    onSuccess: () => {
      setRemoving(false);
      void queryClient.invalidateQueries({ queryKey: ["totp"] });
    },
    // Closed on failure too. What this route refuses with is a step-up
    // challenge, and its answer — the button that sends you back through
    // sign-in — is on the page underneath the dialog.
    onError: () => setRemoving(false),
  });

  if (!status.data) {
    return (
      <Setting
        title="Authenticator app"
        status={status.isError ? "Could not check whether this is set up." : "Checking…"}
        action={
          status.isError ? (
            <Button size="sm" onClick={() => void status.refetch()}>
              Try again
            </Button>
          ) : null
        }
      />
    );
  }

  const removeProblem = remove.error instanceof IdenError ? remove.error : null;
  const confirmProblem = confirm.error instanceof IdenError ? confirm.error : null;

  if (status.data.enrolled) {
    return (
      <Setting
        title="Authenticator app"
        status={
          <span className="flex flex-wrap items-center gap-x-2">
            <StatusDot tone="success" label="On" />
            You'll be asked for a code when an application requires two factors.
          </span>
        }
        action={
          <>
            <Button size="sm" onClick={() => setRemoving(true)}>
              Remove
            </Button>
            <ConfirmDialog
              open={removing}
              onOpenChange={setRemoving}
              title="Remove your authenticator?"
              body="Applications that require two factors will not let you in until you set up a new one."
              confirmLabel="Remove authenticator"
              pending={remove.isPending}
              onConfirm={() => remove.mutate()}
            />
          </>
        }
      >
        {removeProblem ? (
          removeProblem.stepUpMaxAge ? (
            <StepUpNotice problem={removeProblem} />
          ) : (
            <p role="alert" className="text-body-sm text-error">
              {removeProblem.message}
            </p>
          )
        ) : null}
      </Setting>
    );
  }

  return (
    <Setting
      title="Authenticator app"
      status={
        <span className="flex flex-wrap items-center gap-x-2">
          <StatusDot tone="muted" label="Off" />
          An authenticator app gives you a second factor for applications that ask for one.
        </span>
      }
      action={
        enrollment ? (
          <Button size="sm" variant="ghost" onClick={() => setEnrollment(null)}>
            Cancel
          </Button>
        ) : (
          <Button size="sm" disabled={enroll.isPending} onClick={() => enroll.mutate()}>
            {enroll.isPending ? "Preparing…" : "Set up"}
          </Button>
        )
      }
    >
      {enrollment ? (
        <div className="flex flex-col gap-5">
          <p className="text-body-sm text-body">
            Scan this with your authenticator app, then enter the code it shows.
          </p>
          <div className="w-fit rounded-lg bg-canvas p-4 ring-1 ring-hairline">
            <QRCodeSVG value={enrollment.uri} size={168} bgColor="#faf9f5" fgColor="#141413" />
          </div>
          <SecretRevealOnce
            label="Or enter this key by hand"
            secret={enrollment.secret}
            note="Only needed if your app cannot scan the code."
          />
          <Field
            label="Six-digit code"
            error={
              confirmProblem?.code === "totp_wrong_code"
                ? "That code is not right. Codes change every 30 seconds."
                : confirmProblem?.message
            }
          >
            {(props) => (
              <Input
                {...props}
                inputMode="numeric"
                maxLength={6}
                value={code}
                onChange={(event) => setCode(event.target.value)}
                className="font-identity tracking-[0.4em]"
              />
            )}
          </Field>
          <Button
            variant="default"
            className="self-start"
            disabled={confirm.isPending}
            onClick={() => confirm.mutate()}
          >
            {confirm.isPending ? "Checking…" : "Turn on"}
          </Button>
        </div>
      ) : null}
    </Setting>
  );
}
