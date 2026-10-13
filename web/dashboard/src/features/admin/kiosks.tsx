import {
  Button,
  ConfirmDialog,
  DataTable,
  ErrorState,
  Field,
  Input,
  Pagination,
  ScopeChip,
  Spinner,
  StatusDot,
  type Column,
} from "@iden/shared";
import { Plus } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useApi } from "../../app/api";
import { useCountdown } from "../../app/countdown";
import { PageHeader } from "../../app/shell";
import { ago, when } from "../../app/time";
import {
  pairedSince,
  useKiosk,
  useList,
  useWrite,
  type KioskEnrolment,
  type KioskRecord,
  type KioskSettings,
  type PairingCode,
} from "./api";
import { SwitchRow } from "./clients-new";

const STATUS: Record<
  KioskRecord["status"],
  { tone: "success" | "muted" | "error" | "warning"; label: string }
> = {
  online: { tone: "success", label: "Online" },
  offline: { tone: "error", label: "Offline" },
  never_paired: { tone: "muted", label: "Not paired yet" },
  out_of_service: { tone: "warning", label: "Out of service" },
};

const ERRORS: Record<string, string> = {
  poor_capture: "Capture not clear enough",
  not_live: "Failed the liveness checks",
  invalid_frames: "Capture did not match the challenge",
  enrolment_ticket_invalid: "Code expired or already used",
  face_challenge_invalid: "Capture took too long",
  engine_unavailable: "Face engine unavailable",
  kiosk_out_of_service: "Kiosk out of service",
  rate_limited: "Too many attempts",
};

const columns: Column<KioskRecord>[] = [
  { key: "name", header: "Kiosk", cell: (kiosk) => kiosk.name },
  { key: "location", header: "Location", secondary: true, cell: (kiosk) => kiosk.location ?? "—" },
  {
    key: "status",
    header: "Status",
    cell: (kiosk) => (
      <StatusDot tone={STATUS[kiosk.status].tone} label={STATUS[kiosk.status].label} />
    ),
  },
  {
    key: "seen",
    header: "Last seen",
    secondary: true,
    cell: (kiosk) => (kiosk.lastSeenAt ? ago(kiosk.lastSeenAt) : "Never"),
  },
];

export function KiosksRoute() {
  const api = useApi();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const kiosks = useList<KioskRecord>(api, "/admin/kiosks", { offset });

  return (
    <>
      <PageHeader
        title="Kiosks"
        lede="The devices where people enrol their face. Each signs in as itself, and can be switched off or revoked on its own."
        count={kiosks.data?.meta.total}
        actions={
          <Button variant="default" asChild>
            <Link to="/admin/kiosks/new">
              <Plus aria-hidden="true" />
              Register kiosk
            </Link>
          </Button>
        }
      />

      {kiosks.isPending ? (
        <Spinner label="Loading kiosks" />
      ) : kiosks.isError ? (
        <ErrorState error={kiosks.error} onRetry={() => void kiosks.refetch()} />
      ) : (
        <>
          <DataTable
            caption="Kiosks"
            columns={columns}
            rows={kiosks.data.items}
            rowKey={(kiosk) => kiosk.id}
            onRowClick={(kiosk) => void navigate(`/admin/kiosks/${kiosk.id}`)}
          />
          <Pagination meta={kiosks.data.meta} onOffsetChange={setOffset} />
        </>
      )}
    </>
  );
}

/**
 * The code a device trades for its secret, as a QR code for the kiosk camera
 * and as text for its on-screen keypad.
 */
export function PairingPanel({ pairing, onRenew }: { pairing: PairingCode; onRenew: () => void }) {
  const remaining = useCountdown(pairing.expiresAt);

  if (remaining === "0:00") {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-body-sm text-error">This pairing code has expired.</p>
        <Button size="sm" onClick={onRenew}>
          Get a new code
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-prose text-body-sm text-body">
        On the kiosk, show this code to its camera, or type it on the screen. It works once. Pairing
        gives the device its own secret; a device paired before with this kiosk is signed out.
      </p>
      <div className="w-fit rounded-lg bg-canvas p-4 ring-1 ring-hairline">
        <QRCodeSVG
          value={`iden-kiosk-pair:${pairing.code}`}
          size={200}
          bgColor="#faf9f5"
          fgColor="#141413"
        />
      </div>
      <p className="font-identity text-title-lg tracking-widest text-ink">{pairing.code}</p>
      <p className="text-caption text-muted-foreground" aria-live="polite">
        Expires in {remaining}
      </p>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-caption-upper uppercase text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-body-sm text-body">{children}</dd>
    </div>
  );
}

export function KioskDetailRoute() {
  const { kioskId = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const url = `/admin/kiosks/${kioskId}`;
  const [pairing, setPairing] = useState<(PairingCode & { issuedAt: number }) | null>(null);
  const [revoking, setRevoking] = useState(false);
  const kiosk = useKiosk(api, kioskId, pairing !== null);

  const newCode = useWrite<void, PairingCode>([url], async () => {
    const response = await api.post<PairingCode>(`${url}/pairing-code`, {});
    return response.data;
  });
  const issue = () =>
    newCode.mutate(undefined, {
      onSuccess: (code) => setPairing({ ...code, issuedAt: Date.now() }),
    });

  const remove = useWrite<void, void>(["/admin/kiosks"], async () => {
    await api.delete(url);
  });

  if (kiosk.isPending) return <Spinner label="Loading this kiosk" />;
  if (kiosk.isError) return <ErrorState error={kiosk.error} onRetry={() => void kiosk.refetch()} />;

  const record = kiosk.data;
  // The device paired with the code, so it has done its job. Set during render,
  // React's pattern for state derived from a query.
  if (pairing && pairedSince(record, pairing.issuedAt)) setPairing(null);

  return (
    <>
      <Link to="/admin/kiosks" className="text-caption text-muted-foreground hover:text-ink">
        ← Kiosks
      </Link>
      <PageHeader title={record.name} lede={record.location ?? "No location set."} />

      <dl className="mb-10 flex flex-wrap gap-x-12 gap-y-4">
        <Fact label="Status">
          <StatusDot tone={STATUS[record.status].tone} label={STATUS[record.status].label} />
        </Fact>
        <Fact label="Last seen">
          {record.lastSeenAt ? (
            <time dateTime={record.lastSeenAt} title={when(record.lastSeenAt)}>
              {ago(record.lastSeenAt)}
            </time>
          ) : (
            "Never"
          )}
        </Fact>
        <Fact label="Camera">
          {record.lastSeenAt
            ? (record.lastSeenCamera ?? <span className="text-error">None</span>)
            : "—"}
        </Fact>
        <Fact label="Software">{record.lastSeenVersion ?? "—"}</Fact>
        <Fact label="Address">{record.lastSeenAddress ?? "—"}</Fact>
        <Fact label="Client ID">
          <ScopeChip value={record.clientId} />
        </Fact>
      </dl>

      <section className="mb-12">
        <h2 className="mb-1 text-title-lg text-ink">Device</h2>
        {pairing ? (
          <PairingPanel pairing={pairing} onRenew={issue} />
        ) : (
          <>
            <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
              {record.pairedAt
                ? `Paired ${when(record.pairedAt)}. To replace or reinstall the device, pair it again; the old one is signed out.`
                : "No device has paired with this kiosk yet."}
            </p>
            <Button disabled={newCode.isPending} onClick={issue}>
              {record.pairedAt ? "Pair a new device" : "Show pairing code"}
            </Button>
          </>
        )}
        {newCode.error ? <ErrorState error={newCode.error} /> : null}
      </section>

      <SettingsForm key={record.id} url={url} record={record} />

      <History url={url} />

      <section className="border-t border-hairline pt-8">
        <Button variant="destructive" onClick={() => setRevoking(true)}>
          Revoke kiosk
        </Button>
      </section>

      <ConfirmDialog
        open={revoking}
        onOpenChange={setRevoking}
        title={`Revoke ${record.name}?`}
        body="The device stops at once and cannot enrol anyone again. Faces it enrolled stay enrolled. To use it again, register it as a new kiosk."
        confirmLabel="Revoke kiosk"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, { onSuccess: () => void navigate("/admin/kiosks") })
        }
      />
    </>
  );
}

function SettingsForm({ url, record }: { url: string; record: KioskRecord }) {
  const api = useApi();
  const [name, setName] = useState(record.name);
  const [location, setLocation] = useState(record.location ?? "");
  const [settings, setSettings] = useState<KioskSettings>(record.settings);
  const save = useWrite<void, void>([url, "/admin/kiosks"], async () => {
    await api.patch(url, {
      name,
      location: location.trim() || null,
      settings: {
        ...settings,
        notice: settings.notice?.trim() || null,
        cameraLabel: settings.cameraLabel?.trim() || null,
      },
    });
  });
  const set = (patch: Partial<KioskSettings>) =>
    setSettings((current) => ({ ...current, ...patch }));

  return (
    <section className="mb-12">
      <h2 className="mb-1 text-title-lg text-ink">Settings</h2>
      <p className="mb-6 max-w-prose text-body-sm text-muted-foreground">
        The kiosk picks these up within a minute.
      </p>
      <form
        className="flex max-w-xl flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Field
          label="Name"
          required
          hint="People see it in the email telling them their face was enrolled."
        >
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} required />
          )}
        </Field>
        <Field label="Location">
          {(props) => (
            <Input {...props} value={location} onChange={(e) => setLocation(e.target.value)} />
          )}
        </Field>
        <SwitchRow
          checked={settings.inService ?? true}
          onChange={(inService) => set({ inService })}
          label="In service"
          hint="Off: the kiosk shows out of service, and IDEN refuses its enrolments at once."
        />
        <Field label="Clear the screen after" hint="Seconds without a touch, 30 to 600.">
          {(props) => (
            <Input
              {...props}
              type="number"
              min={30}
              max={600}
              value={settings.idleSeconds ?? 90}
              onChange={(e) => set({ idleSeconds: Number(e.target.value) })}
              className="w-32"
            />
          )}
        </Field>
        <Field
          label="Notice"
          hint="One line on the welcome screen — opening hours, where to get help."
        >
          {(props) => (
            <Input
              {...props}
              maxLength={200}
              value={settings.notice ?? ""}
              onChange={(e) => set({ notice: e.target.value })}
            />
          )}
        </Field>
        <Field
          label="Camera"
          hint="Part of the camera's name, when several are attached. Empty uses the first."
        >
          {(props) => (
            <Input
              {...props}
              value={settings.cameraLabel ?? ""}
              onChange={(e) => set({ cameraLabel: e.target.value })}
              placeholder="C280"
            />
          )}
        </Field>
        <div className="flex items-center gap-3">
          <Button type="submit" variant="default" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save settings"}
          </Button>
          {save.isSuccess ? (
            <span className="text-caption text-muted-foreground">Saved.</span>
          ) : null}
        </div>
        {save.error ? <ErrorState error={save.error} /> : null}
      </form>
    </section>
  );
}

const historyColumns: Column<KioskEnrolment>[] = [
  {
    key: "when",
    header: "When",
    cell: (event) => (
      <time dateTime={event.occurredAt} title={when(event.occurredAt)}>
        {ago(event.occurredAt)}
      </time>
    ),
  },
  {
    key: "who",
    header: "Person",
    cell: (event) =>
      event.userId ? (
        <Link to={`/admin/users/${event.userId}`} className="underline">
          {event.userLabel ?? "A deleted account"}
        </Link>
      ) : (
        "—"
      ),
  },
  {
    key: "outcome",
    header: "Outcome",
    cell: (event) =>
      event.outcome === "enrolled" ? (
        <StatusDot tone="success" label="Enrolled" />
      ) : (
        <StatusDot tone="error" label={ERRORS[event.error ?? ""] ?? event.error ?? "Failed"} />
      ),
  },
];

function History({ url }: { url: string }) {
  const api = useApi();
  const [offset, setOffset] = useState(0);
  const events = useList<KioskEnrolment>(api, `${url}/enrolments`, { offset });

  return (
    <section className="mb-12">
      <h2 className="mb-1 text-title-lg text-ink">Enrolments</h2>
      <p className="mb-4 max-w-prose text-body-sm text-muted-foreground">
        Every capture this kiosk sent, and why the failed ones failed. A poor capture is usually the
        light.
      </p>
      {events.isPending ? (
        <Spinner label="Loading enrolments" />
      ) : events.isError ? (
        <ErrorState error={events.error} onRetry={() => void events.refetch()} />
      ) : events.data.items.length === 0 ? (
        <p className="text-body-sm text-muted-foreground">Nothing yet.</p>
      ) : (
        <>
          <DataTable
            caption="Enrolments"
            columns={historyColumns}
            rows={events.data.items}
            rowKey={(event) => event.occurredAt + (event.userId ?? "")}
          />
          <Pagination meta={events.data.meta} onOffsetChange={setOffset} />
        </>
      )}
    </section>
  );
}
