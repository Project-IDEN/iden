import { useQuery } from "@tanstack/react-query";
import { Button, ErrorState, IdenError, Spinner } from "@iden/shared";
import { KeyRound, ScanFace } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { readChallenge, type AuthStep } from "../api";
import { AuthLayout } from "../AuthLayout";
import { CredentialsStep } from "./login-credentials";
import { FaceStep } from "./login-face";
import { TotpStep } from "./login-totp";

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
