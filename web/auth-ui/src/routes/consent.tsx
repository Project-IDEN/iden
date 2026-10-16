import { useMutation, useQuery } from "@tanstack/react-query";
import { AppLogo, Button, ErrorState, IdenError, Notice, ScopeChip, Spinner } from "@iden/shared";
import { useSearchParams } from "react-router";
import { decideConsent, readChallenge } from "../api";
import { AuthLayout } from "../AuthLayout";

/**
 * The consent screen. Its whole job is to make the request legible before it is
 * granted, which is why the scope list is the content and the buttons are not.
 */
export function ConsentRoute() {
  const [params] = useSearchParams();
  const challengeId = params.get("challenge");

  if (!challengeId) {
    return (
      <AuthLayout title="Start from the application">
        <p className="text-body-md text-body">
          This page is opened by an application asking for access. Open the application and try
          again.
        </p>
      </AuthLayout>
    );
  }

  return <ConsentFlow challengeId={challengeId} />;
}

function ConsentFlow({ challengeId }: { challengeId: string }) {
  const challenge = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => readChallenge(challengeId),
    retry: false,
  });

  const decide = useMutation({
    mutationFn: (approved: boolean) => decideConsent({ challengeId, approved }),
    // Both answers are protocol outcomes: approval resumes /authorize, refusal
    // returns the user to the client with error=access_denied.
    onSuccess: (result) => window.location.assign(result.redirectUrl),
  });

  if (challenge.isPending) {
    return (
      <AuthLayout title="Review the request">
        <Spinner label="Reading the request" />
      </AuthLayout>
    );
  }

  if (challenge.isError) {
    const expired = challenge.error instanceof IdenError && challenge.error.status === 404;
    return (
      <AuthLayout title={expired ? "This request expired" : "Review the request"}>
        {expired ? (
          <p className="text-body-md text-body">
            Access requests are valid for a few minutes. Return to the application and start again.
          </p>
        ) : (
          <ErrorState error={challenge.error} onRetry={() => void challenge.refetch()} />
        )}
      </AuthLayout>
    );
  }

  const { clientName, clientLogoUrl, scopes } = challenge.data;

  return (
    <AuthLayout
      eyebrow={clientName}
      title="Allow access?"
      lede={
        <div className="flex items-center gap-4">
          <AppLogo name={clientName} src={clientLogoUrl} size="md" />
          <p className="m-0">
            <span className="text-body-strong">{clientName}</span> is asking to act on your behalf.
            It will be able to:
          </p>
        </div>
      }
    >
      <ul className="m-0 list-none p-0">
        {scopes.map((scope) => (
          <li
            key={scope.value}
            className="flex flex-col gap-1 border-b border-hairline-soft py-3 last:border-b-0"
          >
            <span className="text-body-sm text-body-strong">{scope.description}</span>
            <ScopeChip value={scope.value} className="self-start" />
          </li>
        ))}
      </ul>

      {decide.isError ? (
        <div className="mt-5">
          {decide.error instanceof IdenError && decide.error.status === 401 ? (
            <Notice tone="info" title="Your sign-in timed out">
              Return to the application and start again.
            </Notice>
          ) : (
            <Notice title="Your answer wasn't saved">Try again.</Notice>
          )}
        </div>
      ) : null}

      <div className="mt-8 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Button variant="outline" disabled={decide.isPending} onClick={() => decide.mutate(false)}>
          Deny
        </Button>
        <Button variant="default" disabled={decide.isPending} onClick={() => decide.mutate(true)}>
          {decide.isPending ? "Working…" : "Allow access"}
        </Button>
      </div>

      <p className="mt-5 text-caption text-muted-foreground">
        You can withdraw this at any time from Connections in your account.
      </p>
    </AuthLayout>
  );
}
