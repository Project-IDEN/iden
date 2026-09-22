import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  ErrorState,
  Pagination,
  ScopeChip,
  SecretRevealOnce,
  Spinner,
  type Column,
} from "@iden/shared";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { useList, useRecord, useWrite, type ClientRecord } from "./api";
import { SetPicker } from "./picker";
import { useScopeOptions } from "./options";
import { SystemTag } from "./roles";

const columns: Column<ClientRecord>[] = [
  {
    key: "name",
    header: "Application",
    cell: (client) => (
      <span className="inline-flex items-center gap-2">
        {client.name}
        {client.isSystem ? <SystemTag /> : null}
        {client.ownerUserId ? <Badge variant="outline">self-registered</Badge> : null}
      </span>
    ),
  },
  { key: "clientId", header: "Client ID", cell: (client) => <ScopeChip value={client.clientId} /> },
  {
    key: "type",
    header: "Type",
    secondary: true,
    cell: (client) => (client.clientType === "public" ? "Public (browser)" : "Confidential"),
  },
];

export function ClientsRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const clients = useList<ClientRecord>(api, "/admin/clients", { offset });

  return (
    <>
      <PageHeader
        title="Clients"
        lede="The applications allowed to ask IDEN for tokens — browser apps, mobile apps, and backend services."
        count={clients.data?.meta.total}
        actions={
          <Button variant="default" asChild>
            <Link to="/admin/clients/new">
              <Plus aria-hidden="true" />
              Register client
            </Link>
          </Button>
        }
      />

      {clients.isPending ? (
        <Spinner label="Loading clients" />
      ) : clients.isError ? (
        <ErrorState error={clients.error} onRetry={() => void clients.refetch()} />
      ) : (
        <>
          <DataTable
            caption="Clients"
            columns={columns}
            rows={clients.data.items}
            rowKey={(client) => client.id}
            onRowClick={(client) => void navigate(`/admin/clients/${client.id}`)}
          />
          <Pagination meta={clients.data.meta} onOffsetChange={setOffset} />
        </>
      )}
    </>
  );
}

export function ClientDetailRoute() {
  const { clientId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();

  const client = useRecord<ClientRecord>(api, `/admin/clients/${clientId}`);
  const scopeOptions = useScopeOptions();

  const [grantable, setGrantable] = useState<Set<string> | null>(null);
  const [granted, setGranted] = useState<Set<string> | null>(null);
  const [rotating, setRotating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);

  const invalidates = [`/admin/clients/${clientId}`, "/admin/clients"];

  const saveScopes = useWrite<{ grantableScopeIds: string[]; grantedScopeIds: string[] }, void>(
    invalidates,
    async (body) => {
      await api.put(`/admin/clients/${clientId}/scopes`, body);
    },
  );

  const rotate = useWrite<void, { clientSecret: string }>(invalidates, async () => {
    const response = await api.post<{ clientSecret: string }>(
      `/admin/clients/${clientId}/rotate-secret`,
      {},
    );
    return response.data;
  });

  const remove = useWrite<void, void>(["/admin/clients"], async () => {
    await api.delete(`/admin/clients/${clientId}`);
  });

  if (client.isPending) return <Spinner label="Loading this client" />;
  if (client.isError)
    return <ErrorState error={client.error} onRetry={() => void client.refetch()} />;

  const record = client.data;
  const currentGrantable = new Set(record.grantableScopes.map((scope) => scope.id));
  const currentGranted = new Set(record.grantedScopes.map((scope) => scope.id));
  const chosenGrantable = grantable ?? currentGrantable;
  const chosenGranted = granted ?? currentGranted;
  const changed = grantable !== null || granted !== null;
  const isConfidential = record.clientType === "confidential";

  return (
    <>
      <Link to="/admin/clients" className="text-caption text-muted-foreground hover:text-ink">
        ← Clients
      </Link>

      <PageHeader
        title={record.name}
        lede={
          isConfidential
            ? "A backend service. It authenticates as itself with a secret."
            : "A browser or mobile app. It has no secret and proves itself with PKCE."
        }
      />

      <dl className="mb-10 flex flex-wrap gap-x-12 gap-y-4">
        <div>
          <dt className="text-caption-upper uppercase text-muted-foreground">Client ID</dt>
          <dd className="mt-1">
            <ScopeChip value={record.clientId} />
          </dd>
        </div>
        <div>
          <dt className="text-caption-upper uppercase text-muted-foreground">Grants</dt>
          <dd className="mt-1 text-body-sm text-body">{record.allowedGrants.join(", ")}</dd>
        </div>
        <div>
          <dt className="text-caption-upper uppercase text-muted-foreground">Consent</dt>
          <dd className="mt-1 text-body-sm text-body">
            {record.skipConsent ? "Skipped (first-party)" : "Asked every first time"}
          </dd>
        </div>
        <div>
          <dt className="text-caption-upper uppercase text-muted-foreground">Registered by</dt>
          <dd className="mt-1 text-body-sm text-body">
            {record.ownerUserId ? (
              <Link to={`/admin/users/${record.ownerUserId}`} className="underline">
                A developer
              </Link>
            ) : (
              "The organization"
            )}
          </dd>
        </div>
      </dl>

      {record.redirectUris.length > 0 ? (
        <section className="mb-10">
          <h2 className="mb-2 text-title-md text-ink">Redirect URIs</h2>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {record.redirectUris.map((uri) => (
              <li key={uri}>
                <ScopeChip value={uri} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {scopeOptions.data ? (
        <>
          <section className="mb-12">
            <h2 className="mb-1 text-title-lg text-ink">
              {isConfidential
                ? "Permissions it may request for a user"
                : "Permissions it may request"}
            </h2>
            <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
              The ceiling for what a person can delegate to this app. What they actually get is this
              set intersected with their own permissions.
            </p>
            <SetPicker
              legend="Requestable scopes"
              options={scopeOptions.data}
              selected={chosenGrantable}
              onChange={setGrantable}
              emptyLabel="No scopes are defined yet."
            />
          </section>

          {isConfidential ? (
            <section className="mb-12">
              <h2 className="mb-1 text-title-lg text-ink">Permissions it holds itself</h2>
              <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
                Used with the client credentials grant, where there is no person — the application
                is the identity.
              </p>
              <SetPicker
                legend="Granted scopes"
                options={scopeOptions.data}
                selected={chosenGranted}
                onChange={setGranted}
                emptyLabel="No scopes are defined yet."
              />
            </section>
          ) : null}

          <div className="mb-12 flex items-center gap-3">
            <Button
              variant="default"
              disabled={!changed || saveScopes.isPending}
              onClick={() =>
                saveScopes.mutate(
                  {
                    grantableScopeIds: [...chosenGrantable],
                    grantedScopeIds: [...chosenGranted],
                  },
                  {
                    onSuccess: () => {
                      setGrantable(null);
                      setGranted(null);
                    },
                  },
                )
              }
            >
              {saveScopes.isPending ? "Saving…" : "Save permissions"}
            </Button>
            {changed ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setGrantable(null);
                  setGranted(null);
                }}
              >
                Discard
              </Button>
            ) : null}
          </div>
        </>
      ) : (
        <Spinner label="Loading scopes" />
      )}

      <section className="border-t border-hairline pt-8">
        {secret ? (
          <div className="mb-6">
            <SecretRevealOnce label="New client secret" secret={secret} />
          </div>
        ) : null}
        <div className="flex flex-wrap gap-3">
          {isConfidential ? <Button onClick={() => setRotating(true)}>Rotate secret</Button> : null}
          {record.isSystem ? null : (
            <Button variant="destructive" onClick={() => setDeleting(true)}>
              Delete client
            </Button>
          )}
        </div>
        {record.isSystem ? (
          <p className="mt-4 max-w-prose text-body-sm text-muted-foreground">
            This client ships with IDEN and cannot be deleted — the dashboard you are reading this
            in is registered through it.
          </p>
        ) : null}
      </section>

      <ConfirmDialog
        open={rotating}
        onOpenChange={setRotating}
        title="Rotate this client's secret?"
        body="The current secret stops working immediately. Anything using it fails until it is updated with the new one."
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
        body="It can no longer obtain tokens. Anyone signed in through it is signed out when their current token expires."
        confirmLabel="Delete client"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, { onSuccess: () => void navigate("/admin/clients") })
        }
      />
    </>
  );
}
