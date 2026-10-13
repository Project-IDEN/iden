import { Button, ErrorState, Field, Input } from "@iden/shared";
import { useState } from "react";
import { Link } from "react-router";
import { useApi } from "../../app/api";
import { PageHeader } from "../../app/shell";
import { pairedSince, useKiosk, useWrite, type KioskCreated, type PairingCode } from "./api";
import { PairingPanel } from "./kiosks";

export function KioskCreateRoute() {
  const api = useApi();
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [created, setCreated] = useState<(KioskCreated & { issuedAt: number }) | null>(null);
  const kiosk = useKiosk(api, created?.id ?? "", created !== null);
  const paired = created && kiosk.data ? pairedSince(kiosk.data, created.issuedAt) : false;

  const create = useWrite<void, KioskCreated>(["/admin/kiosks"], async () => {
    const response = await api.post<KioskCreated>("/admin/kiosks", {
      name: name.trim(),
      location: location.trim() || null,
    });
    return response.data;
  });
  const renew = useWrite<void, PairingCode>(["/admin/kiosks"], async () => {
    const response = await api.post<PairingCode>(`/admin/kiosks/${created?.id}/pairing-code`, {});
    return response.data;
  });

  if (created) {
    return (
      <>
        <PageHeader
          title={`Pair ${created.name}`}
          lede="Registered. Now give the device its identity."
        />
        {paired ? (
          <p role="status" className="text-body-md text-ink">
            Paired. The kiosk is ready.
          </p>
        ) : (
          <PairingPanel
            pairing={created.pairing}
            onRenew={() =>
              renew.mutate(undefined, {
                onSuccess: (pairing) => setCreated({ ...created, pairing, issuedAt: Date.now() }),
              })
            }
          />
        )}
        <div className="mt-8 flex gap-3">
          <Button variant="default" asChild>
            <Link to={`/admin/kiosks/${created.id}`}>Open this kiosk</Link>
          </Button>
          <Button variant="ghost" asChild>
            <Link to="/admin/kiosks">Back to kiosks</Link>
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <Link to="/admin/kiosks" className="text-caption text-muted-foreground hover:text-ink">
        ← Kiosks
      </Link>
      <PageHeader
        title="Register a kiosk"
        lede="A device where people enrol their face. You get a pairing code to enter on it."
      />
      <form
        className="flex max-w-xl flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate(undefined, {
            onSuccess: (record) => setCreated({ ...record, issuedAt: Date.now() }),
          });
        }}
      >
        <Field
          label="Name"
          required
          hint="People see it in the email telling them their face was enrolled."
        >
          {(props) => (
            <Input
              {...props}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Library Kiosk 2"
              required
            />
          )}
        </Field>
        <Field label="Location">
          {(props) => (
            <Input
              {...props}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Main library, ground floor"
            />
          )}
        </Field>
        <div>
          <Button type="submit" variant="default" disabled={create.isPending || !name.trim()}>
            {create.isPending ? "Registering…" : "Register kiosk"}
          </Button>
        </div>
        {create.error ? <ErrorState error={create.error} /> : null}
      </form>
    </>
  );
}
