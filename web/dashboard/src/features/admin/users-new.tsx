import { Button, Field, Input, SecretRevealOnce, Spinner } from "@iden/shared";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { z } from "zod";
import { useApi } from "../../app/api";
import { config } from "../../app/config";
import { NotSet, ReviewItem, ReviewList, Wizard, type Step } from "../../app/wizard";
import { useWrite, type UserCreated } from "./api";
import { useGroupOptions, useRoleOptions } from "./options";
import { SetPicker } from "./picker";

const schema = z.object({
  emailLocalPart: z
    .string()
    .min(1, "An email address is required.")
    .max(64, "At most 64 characters.")
    .regex(
      /^[a-zA-Z0-9]+([._-][a-zA-Z0-9]+)*$/,
      "Letters and numbers, with single dots, dashes or underscores between them.",
    ),
  username: z
    .string()
    .min(1, "A username is required.")
    .regex(/^[a-zA-Z0-9._-]+$/, "Letters, numbers, dots, dashes and underscores only."),
  displayName: z.string(),
  roleIds: z.array(z.string()),
  groupIds: z.array(z.string()),
});

type Values = z.infer<typeof schema>;

/** The provider builds the same address; this is only what the form shows. */
const addressOf = (localPart: string) => `${localPart.toLowerCase()}@${config.mailDomain}`;

export function UserCreateRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const roleOptions = useRoleOptions();
  const groupOptions = useGroupOptions();
  const [created, setCreated] = useState<UserCreated | null>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    mode: "onTouched",
    defaultValues: {
      emailLocalPart: "",
      username: "",
      displayName: "",
      roleIds: [],
      groupIds: [],
    },
  });

  const create = useWrite<Values, UserCreated>(["/admin/users"], async (values) => {
    const response = await api.post<UserCreated>("/admin/users", {
      emailLocalPart: values.emailLocalPart,
      username: values.username,
      displayName: values.displayName || null,
      roleIds: values.roleIds,
      groupIds: values.groupIds,
    });
    return response.data;
  });

  const named = (options: { id: string; label: string }[] | undefined, ids: string[]) =>
    (options ?? []).filter((option) => ids.includes(option.id)).map((option) => option.label);

  if (created) {
    return (
      <div className="max-w-xl">
        <h1 className="text-display-md">{created.displayName ?? created.username} added</h1>
        <p className="mt-2 text-body-md text-body">
          Hand this password over directly. It is argon2-hashed on the way in and cannot be shown
          again — you can issue a new one from their page.
        </p>
        {created.generatedPassword ? (
          <div className="mt-6">
            <SecretRevealOnce
              label="One-time password"
              secret={created.generatedPassword}
              note="They should change it after signing in."
            />
          </div>
        ) : null}
        <div className="mt-8 flex gap-3">
          <Button variant="outline" onClick={() => void navigate("/admin/users")}>
            Back to users
          </Button>
          <Button variant="default" onClick={() => void navigate(`/admin/users/${created.id}`)}>
            Open this person
          </Button>
        </div>
      </div>
    );
  }

  const steps: Step<Values>[] = [
    {
      id: "identity",
      label: "Identity",
      title: "Who is this?",
      lede: "The email address is what they sign in with, on this organization's domain. A one-time password is generated and shown once at the end.",
      fields: ["emailLocalPart", "username", "displayName"],
      render: (f) => (
        <div className="flex max-w-xl flex-col gap-6">
          <Field
            label="Email"
            required
            hint="Cannot be changed once the account exists."
            error={f.formState.errors.emailLocalPart?.message}
          >
            {(props) => (
              <div className="flex">
                <Input
                  {...props}
                  {...f.register("emailLocalPart")}
                  autoComplete="off"
                  spellCheck={false}
                  className="rounded-r-none"
                />
                <span className="flex h-control max-w-1/2 shrink-0 items-center truncate rounded-r-md border border-l-0 border-input bg-secondary px-3.5 text-body-md text-muted-foreground">
                  @{config.mailDomain}
                </span>
              </div>
            )}
          </Field>
          <Field
            label="Username"
            required
            hint="Shown to applications as `preferred_username`."
            error={f.formState.errors.username?.message}
          >
            {(props) => <Input {...props} {...f.register("username")} />}
          </Field>
          <Field
            label="Display name"
            hint="How their name appears in applications they sign in to."
            error={f.formState.errors.displayName?.message}
          >
            {(props) => <Input {...props} {...f.register("displayName")} />}
          </Field>
        </div>
      ),
    },
    {
      id: "roles",
      label: "Roles",
      title: "What may they do?",
      lede: "Roles bundle permissions into a job function. Someone with no role can still sign in — they simply cannot do anything yet.",
      render: (f) =>
        roleOptions.isPending ? (
          <Spinner label="Loading roles" />
        ) : (
          <Controller
            control={f.control}
            name="roleIds"
            render={({ field }) => (
              <SetPicker
                legend="Roles"
                options={roleOptions.data ?? []}
                selected={new Set(field.value)}
                onChange={(next) => field.onChange([...next])}
                emptyLabel="No roles are defined yet."
              />
            )}
          />
        ),
    },
    {
      id: "groups",
      label: "Groups",
      title: "Where do they belong?",
      lede: "Membership carries every role the group holds, and decides which profile fields apply to them.",
      render: (f) =>
        groupOptions.isPending ? (
          <Spinner label="Loading groups" />
        ) : (
          <Controller
            control={f.control}
            name="groupIds"
            render={({ field }) => (
              <SetPicker
                legend="Groups"
                options={groupOptions.data ?? []}
                selected={new Set(field.value)}
                onChange={(next) => field.onChange([...next])}
                emptyLabel="No groups exist yet."
              />
            )}
          />
        ),
    },
    {
      id: "review",
      label: "Review",
      title: "Check this before the account exists",
      render: (f) => {
        const v = f.getValues();
        const roles = named(roleOptions.data, v.roleIds);
        const groups = named(groupOptions.data, v.groupIds);
        return (
          <ReviewList>
            <ReviewItem label="Email">{addressOf(v.emailLocalPart)}</ReviewItem>
            <ReviewItem label="Username">{v.username}</ReviewItem>
            <ReviewItem label="Display name">{v.displayName || <NotSet />}</ReviewItem>
            <ReviewItem label="Roles">{roles.length ? roles.join(", ") : <NotSet />}</ReviewItem>
            <ReviewItem label="Groups">{groups.length ? groups.join(", ") : <NotSet />}</ReviewItem>
            <ReviewItem label="Password">Generated, and shown once after this</ReviewItem>
          </ReviewList>
        );
      },
    },
  ];

  return (
    <Wizard
      form={form}
      steps={steps}
      title="Add a user"
      lede="An account for someone in this organization."
      section={{ label: "Users", to: "/admin/users" }}
      backTo="/admin/users"
      backLabel="Back to users"
      submitLabel="Add user"
      pending={create.isPending}
      error={create.error}
      onSubmit={(values) => create.mutate(values, { onSuccess: setCreated })}
    />
  );
}
