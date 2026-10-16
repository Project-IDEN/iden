import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Button,
  ErrorState,
  FaceCapture,
  Field,
  IdenError,
  Input,
  Spinner,
  Notice,
} from "@iden/shared";
import { KeyRound, ScanFace } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router";
import { z } from "zod";
import {
  readChallenge,
  signIn,
  startFaceCheck,
  submitFace,
  submitTotp,
  type AuthStep,
} from "../api";
import { AuthLayout } from "../AuthLayout";
import { duration } from "../duration";
import { FaceOutcome } from "./face-outcome";

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

type Step = "credentials" | "choose" | "otp" | "face";

/** Where to go for the methods still owed: straight to one, or a choice. */
function stepFor(methods: string[]): Step {
  if (methods.length > 1) return "choose";
  return methods[0] === "face" ? "face" : "otp";
}

/**
 * Still working, or done and on the way back to the application. Leaving the
 * page takes a moment after `complete`, and in that moment the step must not
 * offer itself again — the face step would restart the camera.
 */
function working(mutation: { isPending: boolean; data?: AuthStep }): boolean {
  return mutation.isPending || mutation.data?.status === "complete";
}

function LoginFlow({ challengeId, isStepUp }: { challengeId: string; isStepUp: boolean }) {
  const [step, setStep] = useState<Step>();
  const [owedMethods, setOwedMethods] = useState<string[]>();

  const challenge = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => readChallenge(challengeId),
    retry: false,
  });

  /**
   * `complete` hands the request back to the provider, which decides what
   * happens next. `method_required` names what is still owed — a code, a face,
   * or either.
   */
  function advance(result: AuthStep) {
    if (result.status === "method_required") {
      const methods = result.methods ?? [];
      setOwedMethods(methods);
      setStep(stepFor(methods));
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
  // A step-up on a browser that is already signed in owes a method, not the
  // password it gave earlier, so it starts at that method.
  const methods = owedMethods ?? challenge.data.methods ?? [];
  const owed = (challenge.data.methods ?? []).length > 0;
  const current = step ?? (owed ? stepFor(methods) : "credentials");
  const choose = methods.length > 1 ? () => setStep("choose") : undefined;

  if (current === "choose") {
    return <MethodChoice clientName={client} methods={methods} onChoose={setStep} />;
  }

  if (current === "otp") {
    return (
      <TotpStep
        challengeId={challengeId}
        clientName={client}
        isStepUp={owed}
        onDone={advance}
        onSwitch={choose}
      />
    );
  }

  if (current === "face") {
    return (
      <FaceStep challengeId={challengeId} clientName={client} onDone={advance} onSwitch={choose} />
    );
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

function MethodChoice({
  clientName,
  methods,
  onChoose,
}: {
  clientName: string;
  methods: string[];
  onChoose: (step: Step) => void;
}) {
  return (
    <AuthLayout
      eyebrow={clientName}
      step="choose"
      title="One more step"
      lede="Confirm it's you with a second method."
    >
      <div className="flex flex-col gap-3">
        {methods.includes("face") ? (
          <Button variant="default" onClick={() => onChoose("face")}>
            <ScanFace /> Use your face
          </Button>
        ) : null}
        {methods.includes("otp") ? (
          <Button variant="outline" onClick={() => onChoose("otp")}>
            <KeyRound /> Enter a code from your authenticator app
          </Button>
        ) : null}
      </div>
    </AuthLayout>
  );
}

function SwitchMethod({ onSwitch }: { onSwitch?: () => void }) {
  if (!onSwitch) return null;
  return (
    <button
      type="button"
      className="text-primary underline-offset-2 hover:underline"
      onClick={onSwitch}
    >
      Use another method
    </button>
  );
}

/**
 * The face step. Each attempt fetches a fresh challenge — the movements change
 * every time, and a challenge is good for one capture.
 */
function FaceStep({
  challengeId,
  clientName,
  onDone,
  onSwitch,
}: {
  challengeId: string;
  clientName: string;
  onDone: (result: AuthStep) => void;
  onSwitch?: () => void;
}) {
  const [attempt, setAttempt] = useState(0);

  const faceChallenge = useQuery({
    queryKey: ["face-challenge", challengeId, attempt],
    queryFn: () => startFaceCheck(challengeId),
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
  });

  const submit = useMutation({
    mutationFn: (frames: Blob[]) =>
      submitFace({
        challengeId,
        faceChallengeId: faceChallenge.data?.faceChallengeId ?? "",
        frames,
      }),
    onSuccess: onDone,
  });

  const problem =
    submit.error instanceof IdenError
      ? submit.error
      : faceChallenge.error instanceof IdenError
        ? faceChallenge.error
        : null;
  function retry() {
    submit.reset();
    setAttempt((value) => value + 1);
  }

  return (
    <AuthLayout
      eyebrow={clientName}
      step="face"
      title="Confirm it's you"
      lede="Look at the camera and follow the prompts."
      footer={<SwitchMethod onSwitch={onSwitch} />}
    >
      {problem ? (
        <FaceOutcome problem={problem} onRetry={retry} onSwitch={onSwitch} />
      ) : working(submit) ? (
        <Spinner label={submit.isPending ? "Checking it's you" : `Returning to ${clientName}`} />
      ) : faceChallenge.data ? (
        <FaceCapture
          key={faceChallenge.data.faceChallengeId}
          challenge={faceChallenge.data}
          onCaptured={(frames) => submit.mutate(frames)}
        />
      ) : (
        <Spinner label="Preparing the camera" />
      )}
    </AuthLayout>
  );
}

function TotpStep({
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
