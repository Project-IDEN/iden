import {
  Button,
  ErrorState,
  Field,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  SecretRevealOnce,
  Textarea,
} from "@iden/shared";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import { z } from "zod";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { APPLICATIONS, useApplicationWrite, type ApplicationCreated } from "./api";

const lines = (value: string) =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

/**
 * Two kinds, not four.
 *
 * The admin console asks which of four shapes a client is because it can also
 * register a machine-to-machine one. Self-service cannot, so the only question
 * left is whether the app has a backend that can keep a secret.
 */
const KINDS = {
  public: {
    label: "Browser or mobile app",
    hint: "React, Vue, iOS, Android. Anything whose source a user can read cannot keep a secret — PKCE proves it instead.",
  },
  confidential: {
    label: "Server-side app",
    hint: "Next.js, Django, Rails, Express. Runs on a server you control, so it gets a client secret.",
  },
} as const;

const schema = z.object({
  name: z.string().min(1, "Give your app a name."),
  clientType: z.enum(["public", "confidential"]),
  redirectUris: z.string().min(1, "Add at least one redirect URI."),
});

type Values = z.infer<typeof schema>;

export function ApplicationCreateRoute() {
  const api = useApi();
  const [created, setCreated] = useState<ApplicationCreated | null>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    mode: "onTouched",
    defaultValues: { name: "", clientType: "public", redirectUris: "" },
  });

  const create = useApplicationWrite<Values, ApplicationCreated>(null, async (values) => {
    const response = await api.post<ApplicationCreated>(APPLICATIONS, {
      name: values.name,
      clientType: values.clientType,
      redirectUris: lines(values.redirectUris),
    });
    return response.data;
  });

  if (created) return <Handover created={created} />;

  return (
    <>
      <Link
        to="/developer/applications"
        className="text-caption text-muted-foreground hover:text-ink"
      >
        ← Applications
      </Link>

      <PageHeader
        title="Register an app"
        lede="You get a client ID, and people can sign in with IDEN. The name is what they see when they are asked to consent."
      />

      <form
        className="flex max-w-xl flex-col gap-8"
        onSubmit={(event) => {
          event.preventDefault();
          void form.handleSubmit((values) => create.mutate(values, { onSuccess: setCreated }))(
            event,
          );
        }}
      >
        <Field label="Name" required error={form.formState.errors.name?.message}>
          {(props) => <Input {...props} {...form.register("name")} placeholder="Attendance" />}
        </Field>

        <Controller
          control={form.control}
          name="clientType"
          render={({ field }) => (
            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1 text-body-sm text-foreground">What kind of app is it?</legend>
              <RadioGroup value={field.value} onValueChange={field.onChange} className="gap-3">
                {Object.entries(KINDS).map(([value, kind]) => (
                  <div key={value} className="flex items-start gap-3">
                    <RadioGroupItem value={value} id={value} className="mt-1" />
                    <div className="min-w-0">
                      <Label htmlFor={value} className="text-body-sm text-foreground">
                        {kind.label}
                      </Label>
                      <p className="mt-1 text-caption text-muted-foreground">{kind.hint}</p>
                    </div>
                  </div>
                ))}
              </RadioGroup>
              {/* It decides whether a secret exists, and a secret cannot be
                  added to an app that was registered without one. */}
              <p className="text-caption text-muted-soft">Fixed once registered.</p>
            </fieldset>
          )}
        />

        <Field
          label="Redirect URIs"
          required
          hint="Where IDEN sends the browser back. One per line. https anywhere, http on localhost, or a reverse-DNS scheme like com.example.app: for a native app."
          error={form.formState.errors.redirectUris?.message}
        >
          {(props) => (
            <Textarea
              {...props}
              {...form.register("redirectUris")}
              rows={3}
              className="font-identity"
              placeholder={
                "https://attendance.example.org/callback\nhttp://localhost:3000/callback"
              }
            />
          )}
        </Field>

        {create.isError ? <ErrorState error={create.error} /> : null}

        <div className="flex gap-3">
          <Button type="submit" variant="default" disabled={create.isPending}>
            {create.isPending ? "Registering…" : "Register app"}
          </Button>
          <Button type="button" variant="ghost" asChild>
            <Link to="/developer/applications">Cancel</Link>
          </Button>
        </div>
      </form>
    </>
  );
}

/** A confidential app's secret is returned once. That is the whole screen until
    it is dismissed; a public app has none and goes straight to its page. */
function Handover({ created }: { created: ApplicationCreated }) {
  const navigate = useNavigate();
  const open = () => void navigate(`/developer/applications/${created.id}`);

  if (!created.clientSecret) {
    open();
    return null;
  }

  return (
    <div className="max-w-xl">
      <h1 className="text-display-md">{created.name} registered</h1>
      <p className="mt-2 text-body-md text-body">
        Store the secret now. It is hashed on the way in and cannot be shown again — only rotated.
      </p>
      <div className="mt-6 flex flex-col gap-4">
        <SecretRevealOnce label="Client ID" secret={created.clientId} />
        <SecretRevealOnce label="Client secret" secret={created.clientSecret} />
      </div>
      <div className="mt-8">
        <Button variant="default" onClick={open}>
          Open this application
        </Button>
      </div>
    </div>
  );
}
