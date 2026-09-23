import {
  Field,
  Input,
  ScopeChip,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@iden/shared";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { useNavigate } from "react-router";
import { z } from "zod";
import { useApi } from "../../app/api";
import { APP_TYPES, SELF_SERVICE_TYPES, type AppType } from "../../app/app-types";
import { isAbsoluteUri, lines } from "../../app/forms";
import { SecretHandover } from "../../app/handover";
import { NotSet, ReviewItem, ReviewList, Wizard, type Step } from "../../app/wizard";
import { APPLICATIONS, useApplicationWrite, type ApplicationCreated } from "./api";

const schema = z.object({
  name: z.string().min(1, "Give your app a name."),
  appType: z.enum(SELF_SERVICE_TYPES),
  redirectUris: z
    .string()
    .min(1, "Add at least one redirect URI.")
    .refine((value) => lines(value).every(isAbsoluteUri), {
      message: "Each URI must be absolute, including the scheme.",
    }),
  postLogoutRedirectUris: z.string().refine((value) => lines(value).every(isAbsoluteUri), {
    message: "Each URI must be absolute, including the scheme.",
  }),
});

type Values = z.infer<typeof schema>;

export function ApplicationCreateRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const [created, setCreated] = useState<ApplicationCreated | null>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    mode: "onTouched",
    defaultValues: {
      // The safe one to get wrong: a public client has no secret to leak into
      // browser or phone source. The admin console starts on `web` instead,
      // where an administrator is presumed to know which they are registering.
      name: "",
      appType: "spa",
      redirectUris: "",
      postLogoutRedirectUris: "",
    },
  });

  const create = useApplicationWrite<Values, ApplicationCreated>(null, async (values) => {
    const response = await api.post<ApplicationCreated>(APPLICATIONS, {
      name: values.name,
      // `/developer/clients` takes the client type and fixes the grants itself,
      // so the app type only has to survive as far as here.
      clientType: APP_TYPES[values.appType].clientType,
      redirectUris: lines(values.redirectUris),
      postLogoutRedirectUris: lines(values.postLogoutRedirectUris),
    });
    return response.data;
  });

  const appType = useWatch({ control: form.control, name: "appType" }) as AppType;

  if (created?.clientSecret) {
    return (
      <SecretHandover
        name={created.name}
        clientId={created.clientId}
        clientSecret={created.clientSecret}
        listTo="/developer/applications"
        listLabel="Back to applications"
        recordTo={`/developer/applications/${created.id}`}
        recordLabel="Open this application"
      />
    );
  }

  const steps: Step<Values>[] = [
    {
      id: "basics",
      label: "Basics",
      title: "What are you registering?",
      lede: "The name is what people see when they are asked to consent, so name it after the app rather than the project.",
      fields: ["name", "appType"],
      render: (f) => (
        <div className="flex max-w-xl flex-col gap-6">
          <Field label="Name" required error={f.formState.errors.name?.message}>
            {(props) => <Input {...props} {...f.register("name")} placeholder="Attendance" />}
          </Field>

          <Field label="Application type" hint={APP_TYPES[appType].hint}>
            {(props) => (
              <Controller
                control={f.control}
                name="appType"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger {...props} className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SELF_SERVICE_TYPES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {APP_TYPES[value].label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            )}
          </Field>

          {/* What the choice above decided, so the consequence is visible before
              the review rather than only after it. A secret cannot be added to
              an app registered without one. */}
          <p className="-mt-3 text-caption text-muted-soft">
            {APP_TYPES[appType].summary} · fixed once registered
          </p>
        </div>
      ),
    },
    {
      id: "uris",
      label: "URIs",
      title: "Where does IDEN send people back?",
      lede: "Matched exactly — no wildcards, and no forgiveness for a trailing slash. This is what stops an authorization code being delivered somewhere else.",
      fields: ["redirectUris", "postLogoutRedirectUris"],
      render: (f) => (
        <div className="flex max-w-xl flex-col gap-6">
          <Field
            label="Redirect URIs"
            required
            hint="One per line. https anywhere, http on localhost, or a reverse-DNS scheme like com.example.app: for a native app."
            error={f.formState.errors.redirectUris?.message}
          >
            {(props) => (
              <Textarea
                {...props}
                {...f.register("redirectUris")}
                rows={3}
                className="font-identity"
                placeholder={
                  "https://attendance.example.org/callback\nhttp://localhost:3000/callback"
                }
              />
            )}
          </Field>

          <Field
            label="Post-logout redirect URIs"
            hint="Where a sign-out may return the browser. Optional; one per line."
            error={f.formState.errors.postLogoutRedirectUris?.message}
          >
            {(props) => (
              <Textarea
                {...props}
                {...f.register("postLogoutRedirectUris")}
                rows={2}
                className="font-identity"
              />
            )}
          </Field>
        </div>
      ),
    },
    {
      id: "review",
      label: "Review",
      title: "Check this before it exists",
      lede: "The kind of app cannot be changed afterwards. Everything else can.",
      render: (f) => {
        const v = f.getValues();
        const postLogout = lines(v.postLogoutRedirectUris);
        return (
          <ReviewList>
            <ReviewItem label="Name">{v.name}</ReviewItem>
            <ReviewItem label="Type">{APP_TYPES[v.appType].label}</ReviewItem>
            <ReviewItem label="Authentication">{APP_TYPES[v.appType].summary}</ReviewItem>
            <ReviewItem label="Redirect URIs">
              <UriList values={lines(v.redirectUris)} />
            </ReviewItem>
            <ReviewItem label="Post-logout redirect URIs">
              {postLogout.length ? <UriList values={postLogout} /> : <NotSet />}
            </ReviewItem>
            <ReviewItem label="Client ID">Generated by IDEN</ReviewItem>
          </ReviewList>
        );
      },
    },
  ];

  return (
    <Wizard
      form={form}
      steps={steps}
      title="Register an app"
      lede="You get a client ID, and people can sign in with IDEN."
      section={{ label: "Applications", to: "/developer/applications" }}
      backTo="/developer/applications"
      backLabel="Back to applications"
      submitLabel="Register app"
      pending={create.isPending}
      error={create.error}
      onSubmit={(values) =>
        create.mutate(values, {
          onSuccess: (record) => {
            // A public app has no secret, so there is nothing to hand over.
            if (record.clientSecret) setCreated(record);
            else void navigate(`/developer/applications/${record.id}`);
          },
        })
      }
    />
  );
}

/** One per line in the review too, because a URI is long and a comma hides it. */
function UriList({ values }: { values: string[] }) {
  return (
    <span className="flex flex-col items-end gap-1">
      {values.map((value) => (
        <ScopeChip key={value} value={value} />
      ))}
    </span>
  );
}
