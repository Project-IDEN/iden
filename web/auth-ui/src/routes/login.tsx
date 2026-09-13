import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button, ErrorState, Field, IdenError, Input, Spinner } from "@iden/shared";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router";
import { z } from "zod";
import { readChallenge, signIn, submitTotp, type AuthStep } from "../api";
import { AuthLayout } from "../AuthLayout";

const credentials = z.object({
  email: z.string().min(1, "Enter your email address."),
  password: z.string().min(1, "Enter your password."),
});

const totp = z.object({
  code: z.string().regex(/^\d{6}$/, "Enter the six digits from your authenticator app."),
});

/** The provider hands control here; without a challenge there is nothing to resume. */
export function LoginRoute() {
  const [params] = useSearchParams();
  const challengeId = params.get("challenge");
  const isStepUp = params.get("step_up") === "1";

  if (!challengeId) {
    return (
      <AuthLayout title="Start from the application">
        <p className="text-body-md text-body">
          This page is opened by an application that needs you to sign in. Open the application and
          try again.
        </p>
      </AuthLayout>
    );
  }

  return <LoginFlow challengeId={challengeId} isStepUp={isStepUp} />;
}

function LoginFlow({ challengeId, isStepUp }: { challengeId: string; isStepUp: boolean }) {
  const [step, setStep] = useState<"credentials" | "totp">("credentials");

  const challenge = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => readChallenge(challengeId),
    retry: false,
  });

  /** `complete` means the provider can finish the authorization request. */
  function advance(result: AuthStep) {
    if (result.status === "totp_required") {
      setStep("totp");
      return;
    }
    if (result.resumeUrl) window.location.assign(result.resumeUrl);
  }

  if (challenge.isPending) {
    return (
      <AuthLayout title="Sign in">
        <Spinner label="Checking the request" />
      </AuthLayout>
    );
  }

  if (challenge.isError) {
    const problem = challenge.error;
    const expired = problem instanceof IdenError && problem.status === 404;
    return (
      <AuthLayout title={expired ? "This sign-in link expired" : "Sign in"}>
        {expired ? (
          <p className="text-body-md text-body">
            Sign-in requests are valid for a few minutes. Return to the application and start again.
          </p>
        ) : (
          <ErrorState error={problem} onRetry={() => void challenge.refetch()} />
        )}
      </AuthLayout>
    );
  }

  const client = challenge.data.clientName;

  if (step === "totp") {
    return <TotpStep challengeId={challengeId} clientName={client} onDone={advance} />;
  }

  return (
    <CredentialsStep
      challengeId={challengeId}
      clientName={client}
      loginHint={challenge.data.loginHint ?? ""}
      isStepUp={isStepUp}
      onDone={advance}
    />
  );
}

function CredentialsStep({
  challengeId,
  clientName,
  loginHint,
  isStepUp,
  onDone,
}: {
  challengeId: string;
  clientName: string;
  loginHint: string;
  isStepUp: boolean;
  onDone: (result: AuthStep) => void;
}) {
  const form = useForm({
    resolver: zodResolver(credentials),
    defaultValues: { email: loginHint, password: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof credentials>) => signIn({ challengeId, ...values }),
    onSuccess: onDone,
  });

  const problem = mutation.error instanceof IdenError ? mutation.error : null;

  return (
    <AuthLayout
      eyebrow={clientName}
      step="credentials"
      title={isStepUp ? "Confirm it's you" : "Sign in"}
      lede={
        isStepUp
          ? "This application is asking you to enter your password again before it continues."
          : "Enter the credentials for your organization account."
      }
      footer={
        <Link className="text-primary underline-offset-2 hover:underline" to="/auth/forgot">
          Forgot your password?
        </Link>
      }
    >
      <form
        noValidate
        className="flex flex-col gap-5"
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
      >
        <Field label="Email" error={form.formState.errors.email?.message}>
          {(props) => (
            <Input
              {...props}
              {...form.register("email")}
              type="email"
              autoComplete="username"
              autoFocus={!loginHint}
            />
          )}
        </Field>

        <Field label="Password" error={form.formState.errors.password?.message}>
          {(props) => (
            <Input
              {...props}
              {...form.register("password")}
              type="password"
              autoComplete="current-password"
              autoFocus={Boolean(loginHint)}
            />
          )}
        </Field>

        <SignInProblem problem={problem} />

        <Button type="submit" variant="default" disabled={mutation.isPending}>
          {mutation.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}

/**
 * The four ways signing in fails, each said plainly. A wrong password and a
 * deactivated account are different problems with different fixes, and a rate
 * limit is not the person's fault at all.
 */
function SignInProblem({ problem }: { problem: IdenError | null }) {
  if (!problem) return null;

  const message =
    problem.status === 401
      ? "That email and password do not match an account."
      : problem.code === "inactive_user"
        ? "This account has been deactivated. Contact your administrator to restore it."
        : problem.status === 429
          ? `Too many attempts. Try again in ${problem.retryAfter ?? 60} seconds.`
          : problem.status === 404
            ? "This sign-in request expired. Return to the application and start again."
            : problem.message;

  return (
    <p role="alert" className="text-body-sm text-error">
      {message}
    </p>
  );
}

function TotpStep({
  challengeId,
  clientName,
  onDone,
}: {
  challengeId: string;
  clientName: string;
  onDone: (result: AuthStep) => void;
}) {
  const form = useForm({ resolver: zodResolver(totp), defaultValues: { code: "" } });

  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof totp>) => submitTotp({ challengeId, ...values }),
    onSuccess: onDone,
  });

  const problem = mutation.error instanceof IdenError ? mutation.error : null;
  const message =
    problem?.code === "invalid_totp_code"
      ? "That code is not right. Codes change every 30 seconds — try the current one."
      : problem?.status === 401
        ? "Your sign-in timed out. Return to the application and start again."
        : problem?.status === 429
          ? `Too many attempts. Try again in ${problem.retryAfter ?? 60} seconds.`
          : problem?.message;

  return (
    <AuthLayout
      eyebrow={clientName}
      step="totp"
      title="Enter your code"
      lede="Open your authenticator app and enter the six-digit code for this account."
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

        {message ? (
          <p role="alert" className="text-body-sm text-error">
            {message}
          </p>
        ) : null}

        <Button type="submit" variant="default" disabled={mutation.isPending}>
          {mutation.isPending ? "Checking…" : "Continue"}
        </Button>
      </form>
    </AuthLayout>
  );
}
