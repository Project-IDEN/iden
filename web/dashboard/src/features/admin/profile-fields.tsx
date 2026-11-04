import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  IdenError,
  Notice,
  Pagination,
  Row,
  RowCard,
  ScopeChip,
  Spinner,
} from "@iden/shared";
import { Lock, Pencil, Plus, Trash2, UsersRound } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { useList, useWrite, type ProfileFieldRecord } from "./api";
import { SystemTag } from "./roles";

const TYPE_LABELS: Record<string, string> = {
  string: "text",
  integer: "number",
  boolean: "yes/no",
  date: "date",
  enum: "select",
  email: "email",
  phone: "phone",
  url: "url",
};

/**
 * The organization's schema, as a list of definitions rather than a table.
 *
 * A table would give each field one line and force everything interesting into
 * columns that do not fit — the key, the type, who owns it, which group it
 * applies to, and the allowed values of an enum. These are read as definitions,
 * so each gets the room a definition needs.
 */
export function ProfileFieldsRoute() {
  const api = useApi();
  const [offset, setOffset] = useState(0);
  const [deleting, setDeleting] = useState<ProfileFieldRecord | null>(null);

  const fields = useList<ProfileFieldRecord>(api, "/admin/profile-fields", { offset });

  const remove = useWrite<string, void>(["/admin/profile-fields"], async (id) => {
    await api.delete(`/admin/profile-fields/${id}`);
  });

  const problem = remove.error instanceof IdenError ? remove.error : null;

  return (
    <>
      <PageHeader
        title="Profile fields"
        lede="What this organization records about people, beyond name and email. Everyone's self-service profile form is built from this."
        count={fields.data?.meta.total}
        actions={
          <Button variant="default" asChild>
            <Link to="/admin/profile-fields/new">
              <Plus aria-hidden="true" />
              Add field
            </Link>
          </Button>
        }
      />

      {problem ? (
        <div className="mb-4 max-w-prose">
          <Notice title={problem.message} />
        </div>
      ) : null}

      {fields.isPending ? (
        <Spinner label="Loading fields" />
      ) : fields.isError ? (
        <ErrorState error={fields.error} onRetry={() => void fields.refetch()} />
      ) : fields.data.items.length === 0 ? (
        <EmptyState
          title="No fields defined"
          body="Add the things you need to know about people — a department, a student number, a phone extension. Start from a preset if one fits."
          action={
            <Button variant="default" asChild>
              <Link to="/admin/profile-fields/new">Add field</Link>
            </Button>
          }
        />
      ) : (
        <>
          <RowCard>
            {fields.data.items.map((field) => (
              <FieldRow key={field.id} field={field} onDelete={() => setDeleting(field)} />
            ))}
          </RowCard>
          <Pagination meta={fields.data.meta} onOffsetChange={setOffset} />
        </>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.label ?? "this field"}?`}
        body="Every value anyone has entered for it is removed with it. An organization that stops collecting a field should stop holding the data, and nothing else accomplishes that."
        confirmLabel="Delete field"
        pending={remove.isPending}
        onConfirm={() =>
          deleting && remove.mutate(deleting.id, { onSettled: () => setDeleting(null) })
        }
      />
    </>
  );
}

function FieldRow({ field, onDelete }: { field: ProfileFieldRecord; onDelete: () => void }) {
  return (
    <Row className="flex flex-wrap items-start gap-x-5 gap-y-3 py-5">
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2">
          <span className="text-title-sm text-foreground">{field.label}</span>
          <Badge variant="secondary">{TYPE_LABELS[field.dataType] ?? field.dataType}</Badge>
          {field.required ? <Badge>required</Badge> : null}
          {field.unique ? <Badge variant="outline">unique</Badge> : null}
          {field.isSystem ? <SystemTag /> : null}
        </p>

        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <ScopeChip value={field.key} />
          {field.description ? (
            <span className="text-body-sm text-muted-foreground">· {field.description}</span>
          ) : null}
        </p>

        {field.options.length > 0 ? (
          <p className="mt-2 flex flex-wrap gap-1.5">
            {field.options.map((option) => (
              <Badge key={option} variant="secondary">
                {option}
              </Badge>
            ))}
          </p>
        ) : null}

        <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <UsersRound aria-hidden="true" className="h-3.5 w-3.5 text-muted-soft" />
            {field.groupName ? `Members of ${field.groupName}` : "Everyone"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Lock aria-hidden="true" className="h-3.5 w-3.5 text-muted-soft" />
            {field.userWritable ? "Theirs to change" : "Set by administrators"}
          </span>
          {field.claimName ? (
            <span className="inline-flex items-center gap-1.5">
              Released as <span className="font-identity">{field.claimName}</span> under{" "}
              <span className="font-identity">{field.claimScope}</span>
            </span>
          ) : null}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="icon-sm" asChild aria-label={`Edit ${field.label}`}>
          <Link to={`/admin/profile-fields/${field.id}`}>
            <Pencil aria-hidden="true" />
          </Link>
        </Button>
        {field.isSystem ? null : (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Delete ${field.label}`}
            onClick={onDelete}
          >
            <Trash2 aria-hidden="true" />
          </Button>
        )}
      </div>
    </Row>
  );
}
