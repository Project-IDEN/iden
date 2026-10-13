import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  IdenError,
  ProvenanceTrace,
  Row,
  RowCard,
  ScopeChip,
  Spinner,
} from "@iden/shared";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, MonitorSmartphone } from "lucide-react";
import { useState } from "react";
import { useApi } from "../../app/api";
import { useSessionId, useStepUp } from "../../app/session";
import { PageHeader } from "../../app/shell";
import { ago, when } from "../../app/time";
import { useConnections, usePermissions, useSessions, type Sessions } from "./api";

const AMR_LABELS: Record<string, string> = {
  pwd: "Password",
  otp: "Authenticator app",
  face: "Face",
  mfa: "Two factors",
};

type SessionSummary = Sessions["sessions"][number];

/**
 * What to call a session in the list.
 *
 * `device` is best effort — the provider names what it recognises in the
 * User-Agent and returns null otherwise — so an unidentified session gets a
 * label that says only what is actually known rather than a guess.
 */
function title(session: SessionSummary): string {
  if (session.device) return session.device;
  return session.current ? "This browser" : "Another browser";
}

export function SessionsRoute() {
  const api = useApi();
  const sessions = useSessions(api);
  const queryClient = useQueryClient();
  const stepUp = useStepUp();
  const sessionId = useSessionId();
  const [pending, setPending] = useState<string | null>(null);

  const revoke = useMutation({
    mutationFn: (id: string) => api.delete(`/entity/sessions/${id}`),
    onSuccess: () => {
      setPending(null);
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  const problem = revoke.error instanceof IdenError ? revoke.error : null;
  const maxAge = problem?.stepUpMaxAge;

  if (sessions.isPending) return <Spinner label="Loading your sessions" />;
  if (sessions.isError)
    return <ErrorState error={sessions.error} onRetry={() => void sessions.refetch()} />;

  // The provider fills in `current` from the session cookie, which this app
  // never sends, so every row arrives as not-current. The token's `sid` names
  // the same session.
  const rows = sessions.data.sessions.map((session) => ({
    ...session,
    current: session.id === sessionId,
  }));

  return (
    <>
      <PageHeader title="Sessions" lede="Devices and browsers currently signed in." />

      {maxAge ? (
        <div className="mb-6 rounded-lg border border-hairline bg-surface-soft p-5">
          <p className="text-title-sm text-ink">Confirm it's you first</p>
          <p className="mt-1 text-body-sm text-body">
            Signing out a session needs a recent sign-in.
          </p>
          <Button className="mt-4" size="sm" variant="default" onClick={() => stepUp(maxAge)}>
            Enter your password
          </Button>
        </div>
      ) : null}

      {rows.length === 0 ? (
        <EmptyState
          title="No other sessions"
          body="You are signed in from this browser only. Other devices appear here as you use them."
          icon={MonitorSmartphone}
        />
      ) : (
        <RowCard>
          {rows.map((session) => (
            <Row key={session.id} className="flex flex-wrap items-start gap-x-5 gap-y-4 py-5">
              <MonitorSmartphone
                aria-hidden="true"
                className="mt-0.5 h-5 w-5 shrink-0 text-muted-soft"
              />

              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-title-sm text-ink">
                  {title(session)}
                  {session.current ? <Badge variant="default">this device</Badge> : null}
                </p>
                <p className="mt-1 text-caption text-muted-foreground">
                  {[session.browser, session.ip]
                    .filter(Boolean)
                    .concat(session.amr.map((method) => AMR_LABELS[method] ?? method))
                    .join(" · ")}
                </p>
                {session.clients.length > 0 ? (
                  <p className="mt-0.5 text-caption text-muted-soft">
                    Used by {session.clients.join(", ")}
                  </p>
                ) : null}
              </div>

              <div className="shrink-0 text-caption text-muted-foreground tabular-nums">
                <p>
                  Last active{" "}
                  <time dateTime={session.lastSeenAt} title={when(session.lastSeenAt)}>
                    {ago(session.lastSeenAt)}
                  </time>
                </p>
                <p className="mt-0.5 text-muted-soft">
                  signed in{" "}
                  <time dateTime={session.authenticatedAt} title={when(session.authenticatedAt)}>
                    {ago(session.authenticatedAt)}
                  </time>
                </p>
              </div>

              <div className="flex h-8 shrink-0 items-center">
                <Button size="sm" disabled={session.current} onClick={() => setPending(session.id)}>
                  Revoke
                </Button>
              </div>
            </Row>
          ))}
        </RowCard>
      )}

      <p className="mt-4 max-w-prose text-caption text-muted-foreground">
        Revoking a session ends it here and revokes its refresh tokens, so that device cannot reach
        anything again without signing in. Applications that registered for sign-out notices are
        told straight away; the rest find out when they next ask for a token.
      </p>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title="Sign out this session?"
        body="That browser will have to sign in again, and the applications it opened stop working within ten minutes."
        confirmLabel="Sign it out"
        pending={revoke.isPending}
        onConfirm={() => pending && revoke.mutate(pending)}
      />
    </>
  );
}

export function ConnectionsRoute() {
  const api = useApi();
  const connections = useConnections(api);
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<string | null>(null);

  const withdraw = useMutation({
    mutationFn: (clientId: string) => api.delete(`/entity/connections/${clientId}`),
    onSuccess: () => {
      setPending(null);
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });

  if (connections.isPending) return <Spinner label="Loading your connections" />;
  if (connections.isError)
    return <ErrorState error={connections.error} onRetry={() => void connections.refetch()} />;

  return (
    <>
      <PageHeader title="Connections" lede="Applications you have allowed to act on your behalf." />

      {connections.data.connections.length === 0 ? (
        <EmptyState
          title="Nothing has asked for access"
          body="Applications appear here after you allow them on the consent screen. Your organization's own tools don't ask, so they aren't listed."
        />
      ) : (
        <RowCard>
          {connections.data.connections.map((connection) => (
            <Row key={connection.clientId} className="py-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-title-sm text-ink">{connection.name}</p>
                  <p className="mt-0.5 text-caption text-muted-foreground">
                    Allowed {when(connection.grantedAt)}
                  </p>
                </div>
                <Button size="sm" onClick={() => setPending(connection.clientId)}>
                  Withdraw access
                </Button>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {connection.scopes.map((scope) => (
                  <ScopeChip key={scope} value={scope} />
                ))}
              </div>
            </Row>
          ))}
        </RowCard>
      )}

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title="Withdraw this application's access?"
        body="It will have to ask you again the next time you use it."
        confirmLabel="Withdraw access"
        pending={withdraw.isPending}
        onConfirm={() => pending && withdraw.mutate(pending)}
      />
    </>
  );
}

export function PermissionsRoute() {
  const api = useApi();
  const permissions = usePermissions(api);

  if (permissions.isPending) return <Spinner label="Working out your permissions" />;
  if (permissions.isError)
    return <ErrorState error={permissions.error} onRetry={() => void permissions.refetch()} />;

  const { groups, roles, scopes } = permissions.data;

  return (
    <>
      <PageHeader
        title="Permissions"
        lede="What you are allowed to do, and where each permission comes from."
      />

      <dl className="mb-10 flex flex-wrap gap-x-12 gap-y-4">
        <div>
          <dt className="text-caption-upper uppercase text-muted-foreground">Groups</dt>
          <dd className="mt-1 text-body-md text-ink">{groups.join(", ") || "None"}</dd>
        </div>
        <div>
          <dt className="text-caption-upper uppercase text-muted-foreground">Roles</dt>
          <dd className="mt-1 text-body-md text-ink">{roles.join(", ") || "None"}</dd>
        </div>
      </dl>

      {scopes.length === 0 ? (
        <EmptyState
          title="No permissions yet"
          body="An administrator assigns permissions through roles and groups. Ask yours if you expected access to something."
          icon={KeyRound}
        />
      ) : (
        <ProvenanceTrace scopes={scopes} />
      )}
    </>
  );
}
