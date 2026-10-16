import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Button, Field, IdenError, Input, Notice } from "@iden/shared";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { submitTotp, type AuthStep } from "../api";
import { working } from "../auth-step";
import { AuthLayout } from "../AuthLayout";
import { duration } from "../duration";
import { SwitchMethod } from "./switch-method";

const totp = z.object({
  code: z.string().regex(/^\d{6}$/, "Enter the six digits from your authenticator app."),
});

export function TotpStep({
  challengeId,
  clientName,
  isStepUp,
  onDone,
  onSwitch,
}: {
  challengeId: string;
  clientName: string;
  isStepUp: boolean;
  onDone: (result: AuthStep) => void;
  onSwitch?: () => void;
}) {
  const form = useForm({ resolver: zodResolver(totp), defaultValues: { code: "" } });

  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof totp>) => submitTotp({ challengeId, ...values }),
    onSuccess: onDone,
  });

  const problem = mutation.error instanceof IdenError ? mutation.error : null;

  return (
    <AuthLayout
      eyebrow={clientName}
      step="otp"
      footer={<SwitchMethod onSwitch={onSwitch} />}
      title={isStepUp ? "Confirm it's you" : "Enter your code"}
      lede={
        isStepUp
          ? "This application needs a code from your authenticator app before it continues."
          : "Open your authenticator app and enter the six-digit code for this account."
      }
    >
      <form
        noValidate
        className="flex flex-col gap-5"
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
      >
        <Field label="Six-digit code" error={form.formState.errors.code?.message}>
          {(props) => (
            <Input
              {...props}
              {...form.register("code")}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              autoFocus
              className="font-identity tracking-[0.4em]"
            />
          )}
        </Field>

        <TotpProblem problem={problem} />

        <Button type="submit" variant="default" disabled={working(mutation)}>
          {working(mutation) ? "Checking…" : "Continue"}
        </Button>
      </form>
    </AuthLayout>
  );
}

function TotpProblem({ problem }: { problem: IdenError | null }) {
  if (!problem) return null;
  if (problem.code === "invalid_totp_code") {
    return (
      <Notice title="That code didn't work">
        Codes change every 30 seconds, and each works once. Enter the one showing now.
      </Notice>
    );
  }
  if (problem.status === 401) {
    return (
      <Notice tone="info" title="Your sign-in timed out">
        Return to the application and start again.
      </Notice>
    );
  }
  if (problem.status === 429) {
    return (
      <Notice tone="caution" title="Too many attempts">
        Try again in {duration(problem.retryAfter ?? 60)}.
      </Notice>
    );
  }
  return <Notice title={problem.message} />;
}
