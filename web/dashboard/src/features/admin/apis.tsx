import {
  Button,
  ConfirmDialog,
  DataTable,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  EmptyState,
  ErrorState,
  Field,
  IdenError,
  Notice,
  Input,
  Pagination,
  Row,
  RowCard,
  ScopeChip,
  Spinner,
  type Column,
} from "@iden/shared";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { useList, useRecord, useWrite, type ApiRecord, type ScopeRecord } from "./api";
import { SystemTag } from "./roles";

const columns: Column<ApiRecord>[] = [
  {
    key: "name",
    header: "API",
    cell: (record) => (
      <span className="inline-flex items-center gap-2">
        {record.name}
        {record.isSystem ? <SystemTag /> : null}
      </span>
    ),
  },
  {
    key: "audience",
    header: "Audience",
    cell: (record) => <ScopeChip value={record.audience} />,
  },
  { key: "scopes", header: "Scopes", secondary: true, cell: (record) => `${record.scopeCount}` },
];

export function ApisRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const apis = useList<ApiRecord>(api, "/admin/apis", { offset });

  return (
    <>
      <PageHeader
        title="APIs"
        lede="The backends that trust IDEN. Each one defines its own permissions and the audience its tokens carry."
        count={apis.data?.meta.total}
        actions={
          <Button variant="default" asChild>
            <Link to="/admin/apis/new">
              <Plus aria-hidden="true" />
              Register API
            </Link>
          </Button>
        }
      />

      {apis.isPending ? (
        <Spinner label="Loading APIs" />
      ) : apis.isError ? (
        <ErrorState error={apis.error} onRetry={() => void apis.refetch()} />
      ) : (
        <>
          <DataTable
            caption="APIs"
            columns={columns}
            rows={apis.data.items}
            rowKey={(record) => record.id}
            onRowClick={(record) => void navigate(`/admin/apis/${record.id}`)}
          />
          <Pagination meta={apis.data.meta} onOffsetChange={setOffset} />
        </>
      )}
    </>
  );
}

/**
 * Scopes live under their API rather than in a list of their own: a permission
 * belongs to the backend that defines it, which is the point of the model.
 */
export function ApiDetailRoute() {
  const { apiId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();

  const record = useRecord<ApiRecord>(api, `/admin/apis/${apiId}`);
  const scopes = useList<ScopeRecord>(api, `/admin/apis/${apiId}/scopes`, { limit: 200 });
  const [creating, setCreating] = useState(false);
  const [deletingScope, setDeletingScope] = useState<ScopeRecord | null>(null);
  const [deleting, setDeleting] = useState(false);

  const invalidates = [`/admin/apis/${apiId}/scopes`, "/admin/apis", "all-scopes"];

  const removeScope = useWrite<string, void>(invalidates, async (scopeId) => {
    await api.delete(`/admin/scopes/${scopeId}`);
  });

  const remove = useWrite<void, void>(["/admin/apis", "all-scopes"], async () => {
    await api.delete(`/admin/apis/${apiId}`);
  });

  if (record.isPending) return <Spinner label="Loading this API" />;
  if (record.isError)
    return <ErrorState error={record.error} onRetry={() => void record.refetch()} />;

  const removeProblem = remove.error instanceof IdenError ? remove.error : null;
  const scopeProblem = removeScope.error instanceof IdenError ? removeScope.error : null;

  return (
    <>
      <Link to="/admin/apis" className="text-caption text-muted-foreground hover:text-ink">
        ← APIs
      </Link>

      <PageHeader title={record.data.name} lede={record.data.description ?? "No description."} />

      <dl className="mb-10">
        <dt className="text-caption-upper uppercase text-muted-foreground">Audience</dt>
        <dd className="mt-1">
          <ScopeChip value={record.data.audience} />
        </dd>
      </dl>

      {record.data.isSystem ? (
        <p className="mb-8 rounded-lg border border-hairline bg-surface-soft px-5 py-4 text-body-sm text-body">
          This API is part of IDEN itself. Its scopes are what the admin and self-service surfaces
          are gated on, so neither it nor they can be renamed or removed.
        </p>
      ) : null}

      <section className="mb-12">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-title-lg text-ink">Scopes</h2>
          {record.data.isSystem ? null : (
            <Button onClick={() => setCreating(true)}>Define scope</Button>
          )}
        </div>

        {scopeProblem ? (
          <div className="mb-4 max-w-prose">
            {scopeProblem.code === "scope_in_use" ? (
              <Notice title="That scope is still in use">
                A role bundles it or a client is granted it. Remove it there first, or delete it
                anyway to have those references dropped.
              </Notice>
            ) : (
              <Notice title={scopeProblem.message} />
            )}
          </div>
        ) : null}

        {scopes.isPending ? (
          <Spinner label="Loading scopes" />
        ) : scopes.isError ? (
          <ErrorState error={scopes.error} />
        ) : scopes.data.items.length === 0 ? (
          <EmptyState
            title="No scopes defined"
            body="A scope is a single permission this API understands, like records:read. Roles bundle them; clients request them."
            action={<Button onClick={() => setCreating(true)}>Define scope</Button>}
          />
        ) : (
          <RowCard>
            {scopes.data.items.map((scope) => (
              <Row
                key={scope.id}
                className="flex flex-wrap items-center justify-between gap-3 py-3"
              >
                <span className="flex min-w-0 flex-wrap items-baseline gap-3">
                  <ScopeChip value={scope.value} />
                  <span className="text-body-sm text-body">{scope.description}</span>
                </span>
                {scope.isSystem ? (
                  <SystemTag />
                ) : (
                  <Button size="sm" onClick={() => setDeletingScope(scope)}>
                    Delete
                  </Button>
                )}
              </Row>
            ))}
          </RowCard>
        )}
      </section>

      {record.data.isSystem ? null : (
        <section className="border-t border-hairline pt-8">
          {removeProblem ? (
            <div className="mb-4 max-w-prose">
              {removeProblem.code === "api_in_use" ? (
                <Notice title="This API is still in use">
                  Roles or clients still hold its scopes. Remove those references first.
                </Notice>
              ) : (
                <Notice title={removeProblem.message} />
              )}
            </div>
          ) : null}
          <Button variant="destructive" onClick={() => setDeleting(true)}>
            Delete API
          </Button>
        </section>
      )}

      <CreateScopeDialog apiId={apiId} open={creating} onOpenChange={setCreating} />

      <ConfirmDialog
        open={deletingScope !== null}
        onOpenChange={(open) => !open && setDeletingScope(null)}
        title={`Delete ${deletingScope?.value ?? "this scope"}?`}
        body="Any role bundling it and any client allowed to request it lose the reference. People holding it lose the permission at their next token."
        confirmLabel="Delete scope"
        pending={removeScope.isPending}
        onConfirm={() =>
          deletingScope &&
          removeScope.mutate(deletingScope.id, { onSuccess: () => setDeletingScope(null) })
        }
      />

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${record.data.name}?`}
        body="Its scopes go with it. Tokens already minted for this audience stay valid until they expire."
        confirmLabel="Delete API"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => void navigate("/admin/apis"),
            onError: () => setDeleting(false),
          })
        }
      />
    </>
  );
}

function CreateScopeDialog({
  apiId,
  open,
  onOpenChange,
}: {
  apiId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const api = useApi();
  const form = useForm({ defaultValues: { value: "", description: "" } });

  const create = useWrite<{ value: string; description: string }, void>(
    [`/admin/apis/${apiId}/scopes`, "/admin/apis", "all-scopes"],
    async (body) => {
      await api.post(`/admin/apis/${apiId}/scopes`, body);
    },
  );

  const problem = create.error instanceof IdenError ? create.error : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          noValidate
          onSubmit={form.handleSubmit((values) =>
            create.mutate(values, {
              onSuccess: () => {
                onOpenChange(false);
                form.reset();
              },
            }),
          )}
        >
          <DialogTitle className="text-display-sm font-display text-ink">
            Define a scope
          </DialogTitle>
          <DialogDescription className="mt-2 text-body-sm text-body">
            Scope values are unique across the whole deployment, so prefix them with what they
            belong to.
          </DialogDescription>

          <div className="mt-6 flex flex-col gap-5">
            <Field
              label="Value"
              required
              hint="Lowercase, colon-separated — e.g. attendance:records:read"
              error={
                problem?.code === "scope_value_taken"
                  ? "That scope value already exists somewhere in this deployment."
                  : problem?.fieldErrors.find((entry) => entry.field === "value")?.message
              }
            >
              {(props) => (
                <Input {...props} {...form.register("value")} className="font-identity" />
              )}
            </Field>
            <Field
              label="What it allows"
              required
              hint="Shown to people on the consent screen. Write it for them, not for the API."
              error={problem?.fieldErrors.find((entry) => entry.field === "description")?.message}
            >
              {(props) => <Input {...props} {...form.register("description")} />}
            </Field>
          </div>

          <div className="mt-8 flex justify-end gap-3">
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" variant="default" disabled={create.isPending}>
              {create.isPending ? "Defining…" : "Define scope"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
