import {
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@iden/shared";
import { Plus, X } from "lucide-react";
import { Controller, useFieldArray, useWatch, type UseFormReturn } from "react-hook-form";
import { NotSet, ReviewItem, ReviewList } from "../../app/wizard";
import { useGroupOptions } from "./options";
import { DATA_TYPES, type Values } from "./profile-field-form";
import { SwitchRow } from "./switch-row";

type Form = UseFormReturn<Values>;

function SwitchField({
  form,
  name,
  label,
  hint,
}: {
  form: Form;
  name: "required" | "unique" | "userReadable" | "userWritable";
  label: string;
  hint: string;
}) {
  return (
    <Controller
      control={form.control}
      name={name}
      render={({ field }) => (
        <SwitchRow
          id={name}
          checked={field.value}
          onChange={field.onChange}
          label={label}
          hint={hint}
        />
      )}
    />
  );
}

export function DefinitionStep({ form }: { form: Form }) {
  const errors = form.formState.errors;
  const dataType = useWatch({ control: form.control, name: "dataType" });

  return (
    <div className="flex max-w-xl flex-col gap-6">
      <Field label="Label" required error={errors.label?.message}>
        {(props) => <Input {...props} {...form.register("label")} placeholder="Student ID" />}
      </Field>

      <Field
        label="Key"
        required
        hint="The stable identifier. It cannot be changed later, because values are already stored against it."
        error={errors.key?.message}
      >
        {(props) => (
          <Input
            {...props}
            {...form.register("key")}
            className="font-identity"
            placeholder="student_id"
          />
        )}
      </Field>

      <Field label="Description" hint="Shown under the field on the person's own profile form.">
        {(props) => <Textarea {...props} {...form.register("description")} rows={2} />}
      </Field>

      <Field label="Type" hint="Also fixed once values exist — a stored value cannot be recast.">
        {(props) => (
          <Controller
            control={form.control}
            name="dataType"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger {...props} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DATA_TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        )}
      </Field>

      {dataType === "enum" ? <OptionList form={form} /> : null}

      <SwitchField
        form={form}
        name="required"
        label="Required"
        hint="An empty value is refused. Existing people are not asked retroactively."
      />
      <SwitchField
        form={form}
        name="unique"
        label="No two people may share a value"
        hint="Enforced by a database constraint, not a check — two registrations at the same instant cannot both win. Cannot be turned on later."
      />
    </div>
  );
}

function OptionList({ form }: { form: Form }) {
  const options = useFieldArray({ control: form.control, name: "options" });
  const error = form.formState.errors.options?.message;

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="text-caption font-medium text-body-strong">Allowed values</legend>
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
      {error ? <p className="text-caption text-destructive">{error}</p> : null}
      <button
        type="button"
        className="self-start text-caption text-primary hover:underline"
        onClick={() => options.append({ value: "" })}
      >
        <Plus aria-hidden="true" className="mr-1 inline h-3 w-3" />
        Add an option
      </button>
    </fieldset>
  );
}

export function WhoStep({ form }: { form: Form }) {
  const groupOptions = useGroupOptions();

  return (
    <div className="flex max-w-xl flex-col gap-8">
      <Field
        label="Applies to"
        hint="Bound to a group, the field is part of that group's members' profiles and nobody else's. This is how students and staff get different forms without a second grouping concept."
      >
        {(props) => (
          <Controller
            control={form.control}
            name="groupId"
            render={({ field }) => (
              <Select
                value={field.value || "everyone"}
                onValueChange={(value) => field.onChange(value === "everyone" ? "" : value)}
              >
                <SelectTrigger {...props} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="everyone">Everyone in the organization</SelectItem>
                  {(groupOptions.data ?? []).map((group) => (
                    <SelectItem key={group.id} value={group.id}>
                      Members of {group.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        )}
      </Field>

      <SwitchField
        form={form}
        name="userReadable"
        label="They can see it"
        hint="Turn this off for something recorded about a person that they should not be shown."
      />
      <SwitchField
        form={form}
        name="userWritable"
        label="They can change it"
        hint="On means it belongs to the person — a preferred name. Off means it belongs to the organization — a student number, set by whoever issued it."
      />
    </div>
  );
}

export function ReleaseStep({ form }: { form: Form }) {
  const errors = form.formState.errors;
  const claimName = useWatch({ control: form.control, name: "claimName" });

  return (
    <div className="flex max-w-xl flex-col gap-6">
      <Field
        label="Claim name"
        hint="The name it takes in an ID token. Leave empty and this field never leaves IDEN."
        error={errors.claimName?.message}
      >
        {(props) => <Input {...props} {...form.register("claimName")} className="font-identity" />}
      </Field>
      <Field
        label="Claim scope"
        hint="The scope an application must hold to receive it. Must already exist."
        error={errors.claimScope?.message}
      >
        {(props) => (
          <Input
            {...props}
            {...form.register("claimScope")}
            className="font-identity"
            disabled={!claimName}
          />
        )}
      </Field>
    </div>
  );
}

export function ReviewStep({ form }: { form: Form }) {
  const groupOptions = useGroupOptions();
  const v = form.getValues();
  const group = (groupOptions.data ?? []).find((option) => option.id === v.groupId);

  return (
    <ReviewList>
      <ReviewItem label="Label">{v.label}</ReviewItem>
      <ReviewItem label="Key">
        <span className="font-identity">{v.key}</span>
      </ReviewItem>
      <ReviewItem label="Type">
        {DATA_TYPES.find((type) => type.value === v.dataType)?.label}
      </ReviewItem>
      {v.dataType === "enum" ? (
        <ReviewItem label="Options">
          {v.options.map((option) => option.value).join(", ") || <NotSet />}
        </ReviewItem>
      ) : null}
      <ReviewItem label="Applies to">{group ? `Members of ${group.label}` : "Everyone"}</ReviewItem>
      <ReviewItem label="Owned by">
        {v.userWritable
          ? "The person — they can change it"
          : "The organization — read-only to them"}
      </ReviewItem>
      <ReviewItem label="Visible to them">{v.userReadable ? "Yes" : "No"}</ReviewItem>
      <ReviewItem label="Required">{v.required ? "Yes" : "No"}</ReviewItem>
      <ReviewItem label="Unique">{v.unique ? "Yes" : "No"}</ReviewItem>
      <ReviewItem label="Released to applications">
        {v.claimName ? (
          <span className="font-identity">
            {v.claimName} under {v.claimScope}
          </span>
        ) : (
          "Never leaves IDEN"
        )}
      </ReviewItem>
    </ReviewList>
  );
}
