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
  Pagination,
  Row,
  RowCard,
  Spinner,
  type Column,
} from "@iden/shared";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import {
  fetchAll,
  useList,
  useRecord,
  useWrite,
  type GroupRecord,
  type MemberRecord,
  type UserRecord,
} from "./api";
import { SetPicker, type PickerOption } from "./picker";
import { useRoleOptions } from "./options";
import { useQuery } from "@tanstack/react-query";

const columns: Column<GroupRecord>[] = [
  { key: "name", header: "Group", cell: (group) => <span className="text-ink">{group.name}</span> },
  { key: "description", header: "What it is", cell: (group) => group.description ?? "—" },
  {
    key: "roles",
    header: "Roles",
    secondary: true,
    cell: (group) => group.roles.map((role) => role.name).join(", ") || "—",
  },
  { key: "members", header: "People", cell: (group) => `${group.memberCount}` },
];

export function GroupsRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const groups = useList<GroupRecord>(api, "/admin/groups", { offset });

  return (
    <>
      <PageHeader
        title="Groups"
        lede="Departments, teams, cohorts. A group holds roles, and everyone in it inherits them."
        count={groups.data?.meta.total}
        actions={
          <Button variant="default" asChild>
            <Link to="/admin/groups/new">
              <Plus aria-hidden="true" />
              Create group
            </Link>
          </Button>
        }
      />

      {groups.isPending ? (
        <Spinner label="Loading groups" />
      ) : groups.isError ? (
        <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
      ) : groups.data.items.length === 0 ? (
        <EmptyState
          title="No groups yet"
          body="Groups mirror how your organization is actually structured. Create one, give it roles, and add people to it."
          action={
            <Button variant="default" asChild>
              <Link to="/admin/groups/new">Create group</Link>
            </Button>
          }
        />
      ) : (
        <>
          <DataTable
            caption="Groups"
            columns={columns}
            rows={groups.data.items}
            rowKey={(group) => group.id}
            onRowClick={(group) => void navigate(`/admin/groups/${group.id}`)}
          />
          <Pagination meta={groups.data.meta} onOffsetChange={setOffset} />
        </>
      )}
    </>
  );
}

export function GroupDetailRoute() {
  const { groupId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();

  const group = useRecord<GroupRecord>(api, `/admin/groups/${groupId}`);
  const members = useList<MemberRecord>(api, `/admin/groups/${groupId}/members`, { limit: 200 });
  const roleOptions = useRoleOptions();

  const [roles, setRoles] = useState<Set<string> | null>(null);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [removingMember, setRemovingMember] = useState<MemberRecord | null>(null);

  const invalidates = [`/admin/groups/${groupId}`, "/admin/groups"];

  const saveRoles = useWrite<string[], void>(invalidates, async (roleIds) => {
    await api.put(`/admin/groups/${groupId}/roles`, { roleIds });
  });

  const removeMember = useWrite<string, void>(
    [...invalidates, `/admin/groups/${groupId}/members`],
    async (userId) => {
      await api.delete(`/admin/groups/${groupId}/members/${userId}`);
    },
  );

  const remove = useWrite<void, void>(["/admin/groups"], async () => {
    await api.delete(`/admin/groups/${groupId}`);
  });

  if (group.isPending) return <Spinner label="Loading this group" />;
  if (group.isError) return <ErrorState error={group.error} onRetry={() => void group.refetch()} />;

  const record = group.data;
  const current = new Set(record.roles.map((role) => role.id));
  const chosen = roles ?? current;
  const changed = chosen.size !== current.size || [...chosen].some((id) => !current.has(id));

  return (
    <>
      <Link to="/admin/groups" className="text-caption text-muted-foreground hover:text-ink">
        ← Groups
      </Link>

      <PageHeader title={record.name} lede={record.description ?? "No description."} />

      <section className="mb-12">
        <h2 className="mb-3 text-title-lg text-ink">Roles</h2>
        <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
          Everyone in this group inherits these. Saving replaces the whole set.
        </p>
        {roleOptions.data ? (
          <>
            <SetPicker
              legend="Roles"
              options={roleOptions.data}
              selected={chosen}
              onChange={setRoles}
              emptyLabel="No roles defined yet."
            />
            {saveRoles.error ? (
              <div className="mt-3 max-w-prose">
                <ErrorState error={saveRoles.error} />
              </div>
            ) : null}
            <div className="mt-3 flex items-center gap-3">
              <Button
                variant="default"
                disabled={!changed || saveRoles.isPending}
                onClick={() => saveRoles.mutate([...chosen], { onSuccess: () => setRoles(null) })}
              >
                {saveRoles.isPending ? "Saving…" : "Save roles"}
              </Button>
              {changed ? (
                <Button variant="ghost" onClick={() => setRoles(null)}>
                  Discard
                </Button>
              ) : null}
            </div>
          </>
        ) : (
          <Spinner label="Loading roles" />
        )}
      </section>

      <section className="mb-12">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-title-lg text-ink">People</h2>
          <Button onClick={() => setAdding(true)}>Add people</Button>
        </div>

        {removeMember.error ? (
          <div className="mb-4 max-w-prose">
            <ErrorState error={removeMember.error} />
          </div>
        ) : null}

        {members.isPending ? (
          <Spinner label="Loading members" />
        ) : members.isError ? (
          <ErrorState error={members.error} />
        ) : members.data.items.length === 0 ? (
          <EmptyState
            title="Nobody is in this group yet"
            body="Add people and they immediately inherit the roles above."
            action={<Button onClick={() => setAdding(true)}>Add people</Button>}
          />
        ) : (
          <RowCard>
            {members.data.items.map((member) => (
              <Row key={member.id} className="flex items-center justify-between gap-4 py-3">
                <span className="min-w-0">
                  <Link
                    to={`/admin/users/${member.id}`}
                    className="text-body-sm text-ink hover:underline"
                  >
                    {member.displayName ?? member.username}
                  </Link>
                  <span className="ml-2 text-caption text-muted-foreground">{member.email}</span>
                </span>
                <Button size="sm" onClick={() => setRemovingMember(member)}>
                  Remove
                </Button>
              </Row>
            ))}
          </RowCard>
        )}
      </section>

      <section className="border-t border-hairline pt-8">
        {remove.error ? (
          <div className="mb-4 max-w-prose">
            <ErrorState error={remove.error} />
          </div>
        ) : null}
        <Button variant="destructive" onClick={() => setDeleting(true)}>
          Delete group
        </Button>
      </section>

      <AddMembersDialog groupId={groupId} open={adding} onOpenChange={setAdding} />

      <ConfirmDialog
        open={removingMember !== null}
        onOpenChange={(open) => !open && setRemovingMember(null)}
        title="Remove from this group?"
        body={`${removingMember?.displayName ?? removingMember?.username ?? "This person"} loses every role this group holds, unless they have it another way.`}
        confirmLabel="Remove"
        pending={removeMember.isPending}
        onConfirm={() =>
          removingMember &&
          removeMember.mutate(removingMember.id, {
            onSettled: () => setRemovingMember(null),
          })
        }
      />

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${record.name}?`}
        body="Its members keep their accounts but lose the roles this group gave them."
        confirmLabel="Delete group"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => void navigate("/admin/groups"),
            onError: () => setDeleting(false),
          })
        }
      />
    </>
  );
}

function AddMembersDialog({
  groupId,
  open,
  onOpenChange,
}: {
  groupId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const api = useApi();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const people = useQuery({
    queryKey: ["all-users"],
    queryFn: async () => {
      const users = await fetchAll<UserRecord>(api, "/admin/users");
      return users.map((user): PickerOption => ({
        id: user.id,
        label: user.displayName ?? user.username,
        hint: user.email,
      }));
    },
    enabled: open,
  });

  const add = useWrite<string[], void>(
    [`/admin/groups/${groupId}`, `/admin/groups/${groupId}/members`, "/admin/groups"],
    async (userIds) => {
      await api.post(`/admin/groups/${groupId}/members`, { userIds });
    },
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle className="text-display-sm font-display text-ink">Add people</DialogTitle>
        <DialogDescription className="mt-2 text-body-sm text-body">
          Anyone already in the group is left as they are.
        </DialogDescription>

        <div className="mt-6">
          {people.data ? (
            <SetPicker
              legend="People"
              options={people.data}
              selected={selected}
              onChange={setSelected}
              emptyLabel="No users to add."
            />
          ) : (
            <Spinner label="Loading people" />
          )}
        </div>

        {add.error ? (
          <div className="mt-4">
            <ErrorState error={add.error} />
          </div>
        ) : null}

        <div className="mt-8 flex justify-end gap-3">
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button
            variant="default"
            disabled={selected.size === 0 || add.isPending}
            onClick={() =>
              add.mutate([...selected], {
                onSuccess: () => {
                  setSelected(new Set());
                  onOpenChange(false);
                },
              })
            }
          >
            {add.isPending ? "Adding…" : `Add ${selected.size || ""}`.trim()}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
