import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Button, Field, IdenError, Input, Notice } from "@iden/shared";
import { useForm } from "react-hook-form";
import { Link } from "react-router";
import { z } from "zod";
import { signIn, type AuthStep } from "../api";
import { working } from "../auth-step";
import { AuthLayout } from "../AuthLayout";
import { duration } from "../duration";

const credentials = z.object({
  email: z.string().min(1, "Enter your email address."),
  password: z.string().min(1, "Enter your password."),
});

export function CredentialsStep({
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
        // Carries the challenge so recovery can offer the way back. It is the
        // same value already in this page's own URL.
        <Link
          className="text-primary underline-offset-2 hover:underline"
          to={`/auth/forgot?challenge=${encodeURIComponent(challengeId)}`}
        >
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

        <Button type="submit" variant="default" disabled={working(mutation)}>
          {working(mutation) ? "Signing in…" : "Sign in"}
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

  if (problem.status === 401) {
    return (
      <Notice title="That email and password don't match">
        Check both, or reset your password below.
      </Notice>
    );
  }
  if (problem.code === "inactive_user") {
    return (
      <Notice tone="info" title="This account is deactivated">
        Contact your administrator to restore it.
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
  if (problem.status === 404) {
    return (
      <Notice tone="info" title="This sign-in request expired">
        Return to the application and start again.
      </Notice>
    );
  }
  return <Notice title={problem.message} />;
}
