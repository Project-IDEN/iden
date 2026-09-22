import {
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  SearchInput,
  StatusDot,
  Pagination,
  ProvenanceTrace,
  SecretRevealOnce,
  Spinner,
  type Column,
} from "@iden/shared";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { useHasScope } from "../../app/session";
import { PageHeader } from "../../app/shell";
import { useList, useRecord, useWrite, type EffectiveScopes, type UserRecord } from "./api";
import { SetPicker } from "./picker";
import { useRoleOptions, useScopeOptions } from "./options";

const columns: Column<UserRecord>[] = [
  {
    key: "name",
    header: "Person",
    cell: (user) => user.displayName ?? user.username,
  },
  { key: "email", header: "Email", cell: (user) => user.email },
  {
    key: "roles",
    header: "Roles",
    secondary: true,
    cell: (user) => user.roles.map((role) => role.name).join(", ") || "—",
  },
  {
    key: "status",
    header: "Status",
    cell: (user) =>
      user.isActive ? (
        <StatusDot tone="success" label="Active" />
      ) : (
        <StatusDot tone="muted" label="Deactivated" />
      ),
  },
];

export function UsersRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);

  const users = useList<UserRecord>(api, "/admin/users", {
    offset,
    ...(search ? { search } : {}),
  });

  return (
    <>
      <PageHeader
        title="Users"
        lede="Everyone with an account in this organization, and what each of them can do."
        count={users.data?.meta.total}
        actions={
          <Button variant="default" asChild>
            <Link to="/admin/users/new">
              <Plus aria-hidden="true" />
              Add user
            </Link>
          </Button>
        }
      />

      <div className="mb-6">
        <SearchInput
          className="max-w-sm"
          placeholder="Search by name, username or email"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </div>

      {users.isPending ? (
        <Spinner label="Loading users" />
      ) : users.isError ? (
        <ErrorState error={users.error} onRetry={() => void users.refetch()} />
      ) : users.data.items.length === 0 ? (
        <EmptyState
          title={search ? "No one matches that search" : "No users yet"}
          body={
            search
              ? "Try a different name, username, or email address."
              : "Add the people who need accounts. You can assign their roles as you go."
          }
          action={
            search ? undefined : (
              <Button variant="default" asChild>
                <Link to="/admin/users/new">Add user</Link>
              </Button>
            )
          }
        />
      ) : (
        <>
          <DataTable
            caption="Users"
            columns={columns}
            rows={users.data.items}
            rowKey={(user) => user.id}
            onRowClick={(user) => void navigate(`/admin/users/${user.id}`)}
          />
          <Pagination meta={users.data.meta} onOffsetChange={setOffset} />
        </>
      )}
    </>
  );
}

export function UserDetailRoute() {
  const { userId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();

  const user = useRecord<UserRecord>(api, `/admin/users/${userId}`);
  const scopes = useRecord<EffectiveScopes>(api, `/admin/users/${userId}/effective-scopes`);
  const roleOptions = useRoleOptions();
  const scopeOptions = useScopeOptions();

  // Assigning permissions is its own scope. Without it these two sections are
  // read-only: the endpoints behind them refuse, and an editor that saves to a
  // 403 is worse than one that is not offered.
  const mayGrant = useHasScope("admin:grants:write");

  const [deleting, setDeleting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [issued, setIssued] = useState<string | null>(null);

  const setRoles = useWrite<string[], void>(
    [`/admin/users/${userId}`, `/admin/users/${userId}/effective-scopes`],
    async (roleIds) => {
      await api.put(`/admin/users/${userId}/roles`, { roleIds });
    },
  );

  const setScopes = useWrite<string[], void>(
    [`/admin/users/${userId}`, `/admin/users/${userId}/effective-scopes`],
    async (scopeIds) => {
      await api.put(`/admin/users/${userId}/scopes`, { scopeIds });
    },
  );

  const resetPassword = useWrite<void, { password: string | null }>(
    [`/admin/users/${userId}`],
    async () => {
      const response = await api.post<{ password: string | null }>(
        `/admin/users/${userId}/reset-password`,
        {},
      );
      return response.data;
    },
  );

  const remove = useWrite<void, void>(["/admin/users"], async () => {
    await api.delete(`/admin/users/${userId}`);
  });

  if (user.isPending) return <Spinner label="Loading this person" />;
  if (user.isError) return <ErrorState error={user.error} onRetry={() => void user.refetch()} />;

  const record = user.data;
  const selectedScopeIds = new Set(
    (scopeOptions.data ?? [])
      .filter((option) => option.identifier && record.directScopes.includes(option.identifier))
      .map((option) => option.id),
  );

  return (
    <>
      <Link to="/admin/users" className="text-caption text-muted-foreground hover:text-ink">
        ← Users
      </Link>

      <PageHeader
        title={record.displayName ?? record.username}
        lede={`${record.email} · ${record.isActive ? "active" : "deactivated"}`}
      />

      <section className="mb-12">
        <h2 className="mb-3 text-title-lg text-ink">Roles</h2>
        <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
          Roles bundle permissions. Saving replaces the whole set.
        </p>
        {!mayGrant ? (
          <p className="text-body-sm text-body">
            {record.roles.length > 0
              ? record.roles.map((role) => role.name).join(", ")
              : "No roles."}
          </p>
        ) : roleOptions.data ? (
          <RoleEditor
            key={record.roles.map((role) => role.id).join(",")}
            options={roleOptions.data}
            initial={new Set(record.roles.map((role) => role.id))}
            onSave={(ids) => setRoles.mutate([...ids])}
            pending={setRoles.isPending}
          />
        ) : (
          <Spinner label="Loading roles" />
        )}
      </section>

      <section className="mb-12">
        <h2 className="mb-3 text-title-lg text-ink">Direct grants</h2>
        <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
          One-off exceptions that bypass roles. Prefer a role when more than one person needs the
          same thing.
        </p>
        {!mayGrant ? (
          <p className="text-body-sm text-body">
            {record.directScopes.length > 0 ? record.directScopes.join(", ") : "None."}
          </p>
        ) : scopeOptions.data ? (
          <RoleEditor
            key={record.directScopes.join(",")}
            options={scopeOptions.data}
            initial={selectedScopeIds}
            onSave={(ids) => setScopes.mutate([...ids])}
            pending={setScopes.isPending}
            legend="Scopes"
          />
        ) : (
          <Spinner label="Loading scopes" />
        )}
      </section>

      <section className="mb-12">
        <h2 className="mb-3 text-title-lg text-ink">Groups</h2>
        <p className="text-body-sm text-body">
          {record.groups.length > 0
            ? record.groups.map((group) => group.name).join(", ")
            : "Not a member of any group."}
        </p>
        <p className="mt-1 text-caption text-muted-foreground">
          Membership is managed from the group's page.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-3 text-title-lg text-ink">Everything they can do</h2>
        {scopes.isPending ? (
          <Spinner label="Resolving permissions" />
        ) : scopes.isError ? (
          <ErrorState error={scopes.error} />
        ) : scopes.data.scopes.length === 0 ? (
          <p className="text-body-sm text-muted-foreground">No permissions yet.</p>
        ) : (
          <ProvenanceTrace scopes={scopes.data.scopes} />
        )}
      </section>

      <section className="border-t border-hairline pt-8">
        <h2 className="mb-4 text-title-lg text-ink">Account actions</h2>
        {issued ? (
          <div className="mb-6">
            <SecretRevealOnce label="New one-time password" secret={issued} />
          </div>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => setResetting(true)}>Issue a new password</Button>
          <Button variant="destructive" onClick={() => setDeleting(true)}>
            Delete user
          </Button>
        </div>
      </section>

      <ConfirmDialog
        open={resetting}
        onOpenChange={setResetting}
        title="Issue a new password?"
        body="Their current password stops working immediately and every session they have is signed out. You'll get a one-time password to hand over."
        confirmLabel="Issue password"
        destructive={false}
        pending={resetPassword.isPending}
        onConfirm={() =>
          resetPassword.mutate(undefined, {
            onSuccess: (result) => {
              setIssued(result.password);
              setResetting(false);
            },
          })
        }
      />

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${record.displayName ?? record.username}?`}
        body="Their account, sessions and grants are removed. This cannot be undone — deactivating them instead keeps the record."
        confirmLabel="Delete user"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, { onSuccess: () => void navigate("/admin/users") })
        }
      />
    </>
  );
}

/** A picker with its own save button, since these endpoints replace the whole set. */
function RoleEditor({
  options,
  initial,
  onSave,
  pending,
  legend = "Roles",
}: {
  options: { id: string; label: string; identifier?: string; hint?: string }[];
  initial: Set<string>;
  onSave: (ids: Set<string>) => void;
  pending: boolean;
  legend?: string;
}) {
  const [selected, setSelected] = useState(initial);
  const changed = selected.size !== initial.size || [...selected].some((id) => !initial.has(id));

  return (
    <>
      <SetPicker
        legend={legend}
        options={options}
        selected={selected}
        onChange={setSelected}
        emptyLabel={`No ${legend.toLowerCase()} defined yet.`}
      />
      <div className="mt-3 flex items-center gap-3">
        <Button variant="default" disabled={!changed || pending} onClick={() => onSave(selected)}>
          {pending ? "Saving…" : `Save ${legend.toLowerCase()}`}
        </Button>
        {changed ? (
          <Button variant="ghost" onClick={() => setSelected(initial)}>
            Discard
          </Button>
        ) : null}
      </div>
    </>
  );
}
