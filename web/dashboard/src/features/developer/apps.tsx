import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Row,
  RowCard,
  ScopeChip,
  SecretRevealOnce,
  Spinner,
  Textarea,
} from "@iden/shared";
import { AppWindow, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { config } from "../../app/config";
import { PageHeader } from "../../app/shell";
import {
  APPLICATIONS,
  useApplication,
  useApplications,
  useApplicationWrite,
  type Application,
} from "./api";

const lines = (value: string) =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

function kind(application: Application): string {
  return application.clientType === "public"
    ? "Public · browser or mobile"
    : "Confidential · server-side";
}

export function ApplicationsRoute() {
  const api = useApi();
  const applications = useApplications(api);

  if (applications.isPending) return <Spinner label="Loading your applications" />;
  if (applications.isError)
    return <ErrorState error={applications.error} onRetry={() => void applications.refetch()} />;

  const { applications: rows, remaining } = applications.data;

  return (
    <>
      <PageHeader
        title="Applications"
        lede="Your own apps, registered to sign people in with IDEN. Only you can see them."
        count={rows.length}
        actions={
          remaining > 0 ? (
            <Button variant="default" asChild>
              <Link to="/developer/applications/new">
                <Plus aria-hidden="true" />
                Register an app
              </Link>
            </Button>
          ) : null
        }
      />

      {rows.length === 0 ? (
        <EmptyState
          title="No applications yet"
          body="Register one to get a client ID and start signing people in with IDEN."
          icon={AppWindow}
          action={
            <Button variant="default" asChild>
              <Link to="/developer/applications/new">Register an app</Link>
            </Button>
          }
        />
      ) : (
        <RowCard>
          {rows.map((application) => (
            <Row key={application.id} className="flex flex-wrap items-center gap-x-5 gap-y-3">
              <div className="min-w-0 flex-1">
                <p className="text-title-sm text-ink">{application.name}</p>
                <p className="mt-1">
                  <ScopeChip value={application.clientId} />
                </p>
              </div>
              <Badge variant="outline">{kind(application)}</Badge>
              <Button size="sm" asChild>
                <Link to={`/developer/applications/${application.id}`}>Open</Link>
              </Button>
            </Row>
          ))}
        </RowCard>
      )}

      <p className="mt-4 max-w-prose text-caption text-muted-foreground">
        {remaining > 0
          ? `You can register ${remaining} more.`
          : "You have reached the number of applications one account may register. Delete one you no longer need, or ask an administrator."}
      </p>
    </>
  );
}

export function ApplicationDetailRoute() {
  const { applicationId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();

  const application = useApplication(api, applicationId);
  const [uris, setUris] = useState<string | null>(null);
  const [rotating, setRotating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);

  const save = useApplicationWrite<string[], void>(applicationId, async (redirectUris) => {
    await api.patch(`${APPLICATIONS}/${applicationId}`, { redirectUris });
  });

  const rotate = useApplicationWrite<void, { clientSecret: string }>(applicationId, async () => {
    const response = await api.post<{ clientSecret: string }>(
      `${APPLICATIONS}/${applicationId}/rotate-secret`,
      {},
    );
    return response.data;
  });

  const remove = useApplicationWrite<void, void>(null, async () => {
    await api.delete(`${APPLICATIONS}/${applicationId}`);
  });

  if (application.isPending) return <Spinner label="Loading this application" />;
  if (application.isError)
    return <ErrorState error={application.error} onRetry={() => void application.refetch()} />;

  const record = application.data;
  const current = record.redirectUris.join("\n");
  const draft = uris ?? current;
  const changed = uris !== null && uris.trim() !== current;

  return (
    <>
      <Link
        to="/developer/applications"
        className="text-caption text-muted-foreground hover:text-ink"
      >
        ← Applications
      </Link>

      <PageHeader title={record.name} lede={kind(record)} />

      <section className="mb-10">
        <h2 className="mb-1 text-title-lg text-ink">Connection details</h2>
        <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
          Point your OpenID Connect library at the issuer and it discovers the rest.
        </p>
        <dl className="flex flex-wrap gap-x-12 gap-y-4">
          <div>
            <dt className="text-caption-upper uppercase text-muted-foreground">Issuer</dt>
            <dd className="mt-1">
              <ScopeChip value={config.issuer} />
            </dd>
          </div>
          <div>
            <dt className="text-caption-upper uppercase text-muted-foreground">Client ID</dt>
            <dd className="mt-1">
              <ScopeChip value={record.clientId} />
            </dd>
          </div>
          <div>
            <dt className="text-caption-upper uppercase text-muted-foreground">Scopes</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {record.grantableScopes.map((scope) => (
                <ScopeChip key={scope} value={scope} />
              ))}
            </dd>
          </div>
        </dl>
        <p className="mt-4 max-w-prose text-caption text-muted-foreground">
          The authorization code flow with PKCE, and people are asked to consent the first time.
          Need a scope that is not listed, or a token with no user behind it? That is an
          administrator's decision — ask them.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="mb-1 text-title-lg text-ink">Redirect URIs</h2>
        <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
          Matched exactly — a trailing slash is a different URI. This is what stops an authorization
          code being delivered somewhere else.
        </p>
        <div className="max-w-xl">
          <Field
            label="Redirect URIs"
            hint="One per line. https anywhere, http on localhost, or a reverse-DNS scheme for a native app."
            error={save.isError ? "Every URI must be allowed — check the rules above." : undefined}
          >
            {(props) => (
              <Textarea
                {...props}
                rows={4}
                className="font-identity"
                value={draft}
                onChange={(event) => setUris(event.target.value)}
              />
            )}
          </Field>
          <div className="mt-4 flex items-center gap-3">
            <Button
              variant="default"
              disabled={!changed || save.isPending}
              onClick={() => save.mutate(lines(draft), { onSuccess: () => setUris(null) })}
            >
              {save.isPending ? "Saving…" : "Save URIs"}
            </Button>
            {changed ? (
              <Button variant="ghost" onClick={() => setUris(null)}>
                Discard
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      <section className="border-t border-hairline pt-8">
        {secret ? (
          <div className="mb-6 max-w-xl">
            <SecretRevealOnce label="New client secret" secret={secret} />
          </div>
        ) : null}
        <div className="flex flex-wrap gap-3">
          {record.hasSecret ? (
            <Button onClick={() => setRotating(true)}>Rotate secret</Button>
          ) : null}
          <Button variant="destructive" onClick={() => setDeleting(true)}>
            Delete application
          </Button>
        </div>
      </section>

      <ConfirmDialog
        open={rotating}
        onOpenChange={setRotating}
        title="Rotate this application's secret?"
        body="The current secret stops working immediately. Your app fails until it is redeployed with the new one."
        confirmLabel="Rotate secret"
        pending={rotate.isPending}
        onConfirm={() =>
          rotate.mutate(undefined, {
            onSuccess: (result) => {
              setSecret(result.clientSecret);
              setRotating(false);
            },
          })
        }
      />

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${record.name}?`}
        body="It can no longer sign anyone in, and everyone signed in through it is signed out. This cannot be undone."
        confirmLabel="Delete application"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => void navigate("/developer/applications"),
          })
        }
      />
    </>
  );
}
