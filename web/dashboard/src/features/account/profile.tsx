import { Button, ErrorState, Field, IdenError, Input, Notice, Spinner } from "@iden/shared";
import { Lock } from "lucide-react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { IdentityHeader } from "./identity";
import { useProfile, useProfileSchema, useUpdateProfile, type FieldSchema } from "./api";

/**
 * The form is built from `GET /entity/profile/schema`, not from a hardcoded list.
 * Administrators define what this organization collects at runtime, so a form
 * written against today's fields would be wrong by the next deployment.
 */
export function ProfileRoute() {
  const api = useApi();
  const profile = useProfile(api);
  const schema = useProfileSchema(api);
  const update = useUpdateProfile(api);

  // `values` re-seeds the form whenever the query resolves or a save returns,
  // which is what an effect calling setState would otherwise be doing by hand.
  const form = useForm<FormValues>({
    values: {
      displayName: profile.data?.displayName ?? "",
      fields: Object.fromEntries(
        Object.entries(profile.data?.fields ?? {}).map(([key, value]) => [key, stringify(value)]),
      ),
    },
  });

  if (profile.isPending || schema.isPending) return <Spinner label="Loading your profile" />;
  if (profile.isError)
    return <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />;
  if (schema.isError)
    return <ErrorState error={schema.error} onRetry={() => void schema.refetch()} />;

  const writable = schema.data.fields.filter((field) => field.writable);
  const readOnly = schema.data.fields.filter((field) => !field.writable);
  const problem = update.error instanceof IdenError ? update.error : null;

  function submit(values: FormValues) {
    update.mutate({
      displayName: values.displayName || null,
      fields: Object.fromEntries(
        writable.map((field) => [field.key, parse(field, values.fields[field.key] ?? "")]),
      ),
    });
  }

  return (
    <>
      <PageHeader
        title="Profile"
        lede="What this organization records about you, and the parts you can change yourself."
      />

      <IdentityHeader profile={profile.data} />

      <div
        className={
          readOnly.length > 0
            ? "mt-10 grid items-start gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]"
            : "mt-10 max-w-2xl"
        }
      >
        <form noValidate onSubmit={form.handleSubmit(submit)}>
          <h2 className="text-title-lg text-ink">Your details</h2>
          <p className="mt-1 text-body-sm text-muted-foreground">
            Yours to change. Applications you sign in to see your display name.
          </p>

          <div className="mt-6 flex flex-col gap-6">
            <Field
              label="Display name"
              hint="How your name appears to applications you sign in to."
            >
              {(props) => <Input {...props} {...form.register("displayName")} />}
            </Field>

            {writable.map((field) => (
              <Field
                key={field.key}
                label={field.label}
                hint={field.description ?? undefined}
                required={field.required}
                error={fieldError(problem, field.key)}
              >
                {(props) => (
                  <FieldInput
                    {...props}
                    field={field}
                    register={form.register(`fields.${field.key}`)}
                  />
                )}
              </Field>
            ))}
          </div>

          {problem && problem.fieldErrors.length === 0 ? (
            <div className="mt-6 max-w-prose">
              <Notice title={problem.message} />
            </div>
          ) : null}

          <div className="mt-8 flex items-center gap-4 border-t border-hairline-soft pt-6">
            <Button
              type="submit"
              variant="default"
              disabled={update.isPending || !form.formState.isDirty}
            >
              {update.isPending ? "Saving…" : "Save changes"}
            </Button>
            <span aria-live="polite" className="text-caption text-muted-foreground">
              {update.isSuccess && !update.isPending ? "Saved." : ""}
            </span>
          </div>
        </form>

        {readOnly.length > 0 ? (
          <aside className="rounded-lg bg-surface-card p-6">
            <h2 className="flex items-center gap-2 text-title-sm text-ink">
              <Lock aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              Set by your organization
            </h2>
            <p className="mt-1 text-caption text-muted-foreground">
              An administrator maintains these. Ask them if something here is wrong.
            </p>
            {/* Label above value rather than beside it: the column is narrow,
                and a long value set next to its label wraps into a mess. */}
            <dl className="mt-5 flex flex-col gap-4">
              {readOnly.map((field) => (
                <div key={field.key}>
                  <dt className="text-caption text-muted-foreground">{field.label}</dt>
                  <dd className="mt-0.5 text-body-sm break-words text-body-strong">
                    {stringify(profile.data.fields[field.key]) || "—"}
                  </dd>
                </div>
              ))}
            </dl>
          </aside>
        ) : null}
      </div>
    </>
  );
}

interface FormValues {
  displayName: string;
  fields: Record<string, string>;
}

function FieldInput({
  field,
  register,
  ...props
}: {
  field: FieldSchema;
  register: UseFormRegisterReturn;
  id: string;
  "aria-describedby": string | undefined;
  "aria-invalid": boolean;
}) {
  if (field.dataType === "enum") {
    return (
      <select
        {...props}
        {...register}
        className="h-control w-full rounded-md border border-hairline bg-canvas px-3 text-body-md text-ink focus:border-primary focus:outline-none focus:ring-3 focus:ring-primary/15"
      >
        <option value="">Not set</option>
        {field.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }

  if (field.dataType === "boolean") {
    return (
      <select
        {...props}
        {...register}
        className="h-control w-full rounded-md border border-hairline bg-canvas px-3 text-body-md text-ink focus:border-primary focus:outline-none focus:ring-3 focus:ring-primary/15"
      >
        <option value="">Not set</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }

  return <Input {...props} {...register} type={inputType(field.dataType)} />;
}

function inputType(dataType: string): string {
  if (dataType === "integer") return "number";
  if (dataType === "date") return "date";
  if (dataType === "email") return "email";
  if (dataType === "url") return "url";
  if (dataType === "phone") return "tel";
  return "text";
}

function stringify(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

/** The server validates properly; this only restores the JSON type it expects. */
function parse(field: FieldSchema, value: string): unknown {
  if (value === "") return null;
  if (field.dataType === "integer") return Number(value);
  if (field.dataType === "boolean") return value === "true";
  return value;
}

function fieldError(problem: IdenError | null, key: string): string | undefined {
  if (!problem) return undefined;
  // A per-field 422 names the field; the single-field domain errors put the key
  // in `details` instead.
  const named = problem.fieldErrors.find((entry) => entry.field.endsWith(key));
  if (named) return named.message;
  return problem.details.field === key ? problem.message : undefined;
}
