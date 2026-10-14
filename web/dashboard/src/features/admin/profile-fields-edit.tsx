import {
  Badge,
  Button,
  Card,
  CardContent,
  ErrorState,
  Field,
  Input,
  ScopeChip,
  Spinner,
  Textarea,
} from "@iden/shared";
import { ArrowLeft, Plus, X } from "lucide-react";
import { useEffect } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { useRecord, useWrite, type ProfileFieldRecord } from "./api";
import { SwitchRow } from "./switch-row";

interface Values {
  label: string;
  description: string;
  options: { value: string }[];
  required: boolean;
  userReadable: boolean;
  userWritable: boolean;
  claimName: string;
  claimScope: string;
  displayOrder: number;
}

/**
 * Editing a field, which is deliberately less than defining one.
 *
 * `key`, `dataType`, `unique` and `groupId` are absent because the server
 * refuses them: each would rewrite the meaning of values already stored. The
 * page says so rather than showing disabled inputs, because a disabled input
 * invites a bug report about why it is disabled.
 */
export function ProfileFieldEditRoute() {
  const { fieldId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();

  const record = useRecord<ProfileFieldRecord>(api, `/admin/profile-fields/${fieldId}`);

  const form = useForm<Values>({
    defaultValues: {
      label: "",
      description: "",
      options: [],
      required: false,
      userReadable: true,
      userWritable: false,
      claimName: "",
      claimScope: "",
      displayOrder: 0,
    },
  });
  const options = useFieldArray({ control: form.control, name: "options" });

  useEffect(() => {
    if (!record.data) return;
    form.reset({
      label: record.data.label,
      description: record.data.description ?? "",
      options: record.data.options.map((value) => ({ value })),
      required: record.data.required,
      userReadable: record.data.userReadable,
      userWritable: record.data.userWritable,
      claimName: record.data.claimName ?? "",
      claimScope: record.data.claimScope ?? "",
      displayOrder: record.data.displayOrder,
    });
  }, [record.data, form]);

  const save = useWrite<Values, ProfileFieldRecord>(
    ["/admin/profile-fields", `/admin/profile-fields/${fieldId}`],
    async (values) => {
      const response = await api.patch<ProfileFieldRecord>(`/admin/profile-fields/${fieldId}`, {
        label: values.label,
        description: values.description || null,
        options: values.options.map((option) => option.value),
        required: values.required,
        userReadable: values.userReadable,
        userWritable: values.userWritable,
        claimName: values.claimName || null,
        claimScope: values.claimScope || null,
        displayOrder: Number(values.displayOrder),
      });
      return response.data;
    },
  );

  if (record.isPending) return <Spinner label="Loading this field" />;
  if (record.isError) {
    return <ErrorState error={record.error} onRetry={() => void record.refetch()} />;
  }

  const field = record.data;

  return (
    <>
      <Link
        to="/admin/profile-fields"
        className="inline-flex items-center gap-1.5 text-caption text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
        Back to profile fields
      </Link>

      <PageHeader title={field.label} lede="What this field collects, and who it belongs to." />

      <section className="mb-8 max-w-xl rounded-lg bg-surface-card p-6">
        <h2 className="text-title-sm text-foreground">Fixed for the life of the field</h2>
        <p className="mt-1 text-body-sm text-muted-foreground">
          Each of these would rewrite the meaning of values already stored, so the server refuses
          them. Define a new field instead.
        </p>
        <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
          <div>
            <dt className="text-caption-upper uppercase text-muted-foreground">Key</dt>
            <dd className="mt-1">
              <ScopeChip value={field.key} />
            </dd>
          </div>
          <div>
            <dt className="text-caption-upper uppercase text-muted-foreground">Type</dt>
            <dd className="mt-1 text-body-sm text-body">{field.dataType}</dd>
          </div>
          <div>
            <dt className="text-caption-upper uppercase text-muted-foreground">Applies to</dt>
            <dd className="mt-1 text-body-sm text-body">
              {field.groupName ? `Members of ${field.groupName}` : "Everyone"}
            </dd>
          </div>
          <div>
            <dt className="text-caption-upper uppercase text-muted-foreground">Unique</dt>
            <dd className="mt-1 text-body-sm text-body">{field.unique ? "Yes" : "No"}</dd>
          </div>
        </dl>
      </section>

      <form
        className="max-w-xl"
        onSubmit={form.handleSubmit((values) =>
          save.mutate(values, { onSuccess: () => void navigate("/admin/profile-fields") }),
        )}
      >
        <Card>
          <CardContent className="flex flex-col gap-6">
            <Field label="Label" required>
              {(props) => <Input {...props} {...form.register("label")} />}
            </Field>
            <Field label="Description" hint="Shown under the field on the person's own form.">
              {(props) => <Textarea {...props} {...form.register("description")} rows={2} />}
            </Field>

            {field.dataType === "enum" ? (
              <fieldset className="flex flex-col gap-3">
                <legend className="text-caption font-medium text-body-strong">
                  Allowed values
                </legend>
                <p className="text-caption text-muted-foreground">
                  Removing one does not rewrite anybody's stored answer.
                </p>
                {options.fields.map((entry, index) => (
                  <div key={entry.id} className="flex items-center gap-2">
                    <Input {...form.register(`options.${index}.value`)} />
                    <button
                      type="button"
                      aria-label="Remove this option"
                      className="rounded-md p-2 text-muted-soft hover:bg-secondary hover:text-foreground"
                      onClick={() => options.remove(index)}
                    >
                      <X aria-hidden="true" className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="self-start text-caption text-primary hover:underline"
                  onClick={() => options.append({ value: "" })}
                >
                  <Plus aria-hidden="true" className="mr-1 inline h-3 w-3" />
                  Add an option
                </button>
              </fieldset>
            ) : null}

            <Field label="Display order" hint="Lower numbers come first on the form.">
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  {...form.register("displayOrder")}
                  className="w-32"
                />
              )}
            </Field>

            <div className="flex flex-col gap-5 border-t border-hairline-soft pt-6">
              <Toggle form={form} name="required" label="Required" />
              <Toggle form={form} name="userReadable" label="They can see it" />
              <Toggle
                form={form}
                name="userWritable"
                label="They can change it"
                hint="On means the field belongs to the person; off means it belongs to the organization."
              />
            </div>

            <div className="flex flex-col gap-5 border-t border-hairline-soft pt-6">
              <p className="text-title-sm text-foreground">
                Release to applications
                {field.claimName ? null : (
                  <Badge variant="outline" className="ml-2">
                    off
                  </Badge>
                )}
              </p>
              <Field label="Claim name" hint="Leave empty and this field never leaves IDEN.">
                {(props) => (
                  <Input {...props} {...form.register("claimName")} className="font-identity" />
                )}
              </Field>
              <Field label="Claim scope" hint="The scope an application must hold to receive it.">
                {(props) => (
                  <Input {...props} {...form.register("claimScope")} className="font-identity" />
                )}
              </Field>
            </div>
          </CardContent>
        </Card>

        {save.error ? (
          <div className="mt-6">
            <ErrorState error={save.error} />
          </div>
        ) : null}

        <div className="mt-8 flex items-center gap-3">
          <Button type="submit" variant="default" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save changes"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void navigate("/admin/profile-fields")}
          >
            Cancel
          </Button>
        </div>
      </form>
    </>
  );
}

function Toggle({
  form,
  name,
  label,
  hint,
}: {
  form: ReturnType<typeof useForm<Values>>;
  name: "required" | "userReadable" | "userWritable";
  label: string;
  hint?: string;
}) {
  return (
    <SwitchRow
      id={name}
      checked={form.watch(name)}
      onChange={(next) => form.setValue(name, next, { shouldDirty: true })}
      label={label}
      hint={hint}
    />
  );
}
