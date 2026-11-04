import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  ErrorState,
  IdenError,
  Notice,
  Pagination,
  Row,
  RowCard,
  ScopeChip,
  Spinner,
  type Column,
} from "@iden/shared";
import { Lock, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { useList, useRecord, useWrite, type RoleRecord } from "./api";
import { SetPicker } from "./picker";
import { useScopeOptions } from "./options";

const columns: Column<RoleRecord>[] = [
  {
    key: "name",
    header: "Role",
    cell: (role) => (
      <span className="inline-flex items-center gap-2">
        {role.name}
        {role.isSystem ? <SystemTag /> : null}
      </span>
    ),
  },
  { key: "description", header: "What it is for", cell: (role) => role.description ?? "—" },
  {
    key: "scopes",
    header: "Permissions",
    secondary: true,
    cell: (role) => `${role.scopes.length}`,
  },
];

/** System records cannot be renamed or deleted — say so before anyone tries. */
export function SystemTag() {
  return (
    <Badge variant="outline">
      <Lock aria-hidden="true" className="h-3 w-3" />
      built in
    </Badge>
  );
}

export function RolesRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const roles = useList<RoleRecord>(api, "/admin/roles", { offset });

  return (
    <>
      <PageHeader
        title="Roles"
        lede="Named bundles of permissions — a job function like attendance-officer. One role can span several APIs."
        count={roles.data?.meta.total}
        actions={
          <Button variant="default" asChild>
            <Link to="/admin/roles/new">
              <Plus aria-hidden="true" />
              Create role
            </Link>
          </Button>
        }
      />

      {roles.isPending ? (
        <Spinner label="Loading roles" />
      ) : roles.isError ? (
        <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />
      ) : (
        <>
          <DataTable
            caption="Roles"
            columns={columns}
            rows={roles.data.items}
            rowKey={(role) => role.id}
            onRowClick={(role) => void navigate(`/admin/roles/${role.id}`)}
          />
          <Pagination meta={roles.data.meta} onOffsetChange={setOffset} />
        </>
      )}
    </>
  );
}

export function RoleDetailRoute() {
  const { roleId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();

  const role = useRecord<RoleRecord>(api, `/admin/roles/${roleId}`);
  const scopeOptions = useScopeOptions();
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [deleting, setDeleting] = useState(false);

  const save = useWrite<string[], void>([`/admin/roles/${roleId}`, "/admin/roles"], async (ids) => {
    await api.put(`/admin/roles/${roleId}/scopes`, { scopeIds: ids });
  });

  const remove = useWrite<void, void>(["/admin/roles", "all-roles"], async () => {
    await api.delete(`/admin/roles/${roleId}`);
  });

  if (role.isPending) return <Spinner label="Loading this role" />;
  if (role.isError) return <ErrorState error={role.error} onRetry={() => void role.refetch()} />;

  const record = role.data;
  const current = new Set(record.scopes.map((scope) => scope.id));
  const chosen = selected ?? current;
  const changed = chosen.size !== current.size || [...chosen].some((id) => !current.has(id));

  const saveProblem = save.error instanceof IdenError ? save.error : null;
  const removeProblem = remove.error instanceof IdenError ? remove.error : null;

  return (
    <>
      <Link to="/admin/roles" className="text-caption text-muted-foreground hover:text-ink">
        ← Roles
      </Link>

      <PageHeader title={record.name} lede={record.description ?? "No description."} />

      {record.isSystem ? (
        <p className="mb-8 rounded-lg border border-hairline bg-surface-soft px-5 py-4 text-body-sm text-body">
          This role is part of IDEN itself. Its name and permissions are fixed, because removing
          them could lock this organization out of its own deployment.
        </p>
      ) : null}

      <section className="mb-12">
        <h2 className="mb-3 text-title-lg text-ink">Permissions</h2>
        {record.isSystem ? (
          <RowCard>
            {record.scopes.map((scope) => (
              <Row key={scope.id} className="flex flex-wrap items-baseline gap-3 py-2.5">
                <ScopeChip value={scope.value} />
                <span className="text-body-sm text-body">{scope.description}</span>
              </Row>
            ))}
          </RowCard>
        ) : scopeOptions.data ? (
          <>
            <SetPicker
              legend="Scopes"
              options={scopeOptions.data}
              selected={chosen}
              onChange={setSelected}
              emptyLabel="No scopes are defined yet. Register an API and define its scopes first."
            />
            {saveProblem ? (
              <div className="mt-3 max-w-prose">
                <Notice title={saveProblem.message} />
              </div>
            ) : null}
            <div className="mt-3 flex items-center gap-3">
              <Button
                variant="default"
                disabled={!changed || save.isPending}
                onClick={() => save.mutate([...chosen], { onSuccess: () => setSelected(null) })}
              >
                {save.isPending ? "Saving…" : "Save permissions"}
              </Button>
              {changed ? (
                <Button variant="ghost" onClick={() => setSelected(null)}>
                  Discard
                </Button>
              ) : null}
            </div>
          </>
        ) : (
          <Spinner label="Loading scopes" />
        )}
      </section>

      {record.isSystem ? null : (
        <section className="border-t border-hairline pt-8">
          {removeProblem ? (
            <div className="mb-4 max-w-prose">
              {removeProblem.code === "role_in_use" ? (
                <Notice title="This role is still assigned">
                  People or groups still hold it. Remove those assignments first.
                </Notice>
              ) : (
                <Notice title={removeProblem.message} />
              )}
            </div>
          ) : null}
          <Button variant="destructive" onClick={() => setDeleting(true)}>
            Delete role
          </Button>
        </section>
      )}

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${record.name}?`}
        body="Anyone holding this role loses the permissions it bundles the next time they receive a token."
        confirmLabel="Delete role"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => void navigate("/admin/roles"),
            onError: () => setDeleting(false),
          })
        }
      />
    </>
  );
}
