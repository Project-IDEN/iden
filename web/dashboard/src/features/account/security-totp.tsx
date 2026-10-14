import {
  Button,
  ConfirmDialog,
  Field,
  IdenError,
  Input,
  SecretRevealOnce,
  StatusDot,
} from "@iden/shared";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { useApi } from "../../app/api";
import { useTotpStatus, type TotpEnrollment, type TotpStatus } from "./api";
import { PendingSetting, Problem, Setting } from "./security-setting";

const TITLE = "Authenticator app";

export function TotpSetting() {
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
      <PendingSetting
        title={TITLE}
        failed={status.isError}
        failure="Could not check whether this is set up."
        onRetry={() => void status.refetch()}
      />
    );
  }

  if (status.data.enrolled) {
    const removeProblem = remove.error instanceof IdenError ? remove.error : null;
    return (
      <Setting
        title={TITLE}
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
        {removeProblem ? <Problem problem={removeProblem} /> : null}
      </Setting>
    );
  }

  const enrollProblem = enroll.error instanceof IdenError ? enroll.error : null;
  const confirmProblem = confirm.error instanceof IdenError ? confirm.error : null;

  return (
    <Setting
      title={TITLE}
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
      ) : enrollProblem ? (
        // Setting up needs a recent sign-in. Without this, a refusal past five
        // minutes left the button doing nothing at all.
        <Problem problem={enrollProblem} />
      ) : null}
    </Setting>
  );
}
