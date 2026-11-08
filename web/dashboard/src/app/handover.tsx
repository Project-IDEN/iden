import { Button, CopyableValue, Notice, SecretRevealOnce } from "@iden/shared";
import { Link } from "react-router";

/**
 * The last screen of a registration that produced a secret.
 *
 * It is the whole screen rather than a panel on the record, because this is the
 * only moment the secret exists in readable form and a page with somewhere else
 * to click is a page somebody clicks away from.
 *
 * `clientId` is shown only where IDEN generated it. An administrator chose
 * theirs and already knows it; a developer does not. It is not a secret and is
 * on the application's page for good, so it is offered for copying here but
 * not labelled "shown once" — only the secret is.
 */
export function SecretHandover({
  name,
  clientId,
  clientSecret,
  listTo,
  listLabel,
  recordTo,
  recordLabel,
  notice,
}: {
  name: string;
  clientId?: string;
  clientSecret: string;
  listTo: string;
  listLabel: string;
  recordTo: string;
  recordLabel: string;
  /** Something that went wrong after the registration itself succeeded. */
  notice?: string;
}) {
  return (
    <div className="max-w-xl">
      <h1 className="text-display-md">{name} registered</h1>
      <p className="mt-2 text-body-md text-body">
        Store the secret now. It is argon2-hashed on the way in and cannot be shown again — only
        rotated.
      </p>

      <div className="mt-6 flex flex-col gap-4">
        {clientId ? (
          <CopyableValue
            label="Client ID"
            value={clientId}
            note="Not a secret — it stays on this application's page, so you can copy it again any time."
          />
        ) : null}
        <SecretRevealOnce label="Client secret" secret={clientSecret} />
      </div>

      {notice ? (
        <div className="mt-4">
          <Notice tone="caution" title={notice} />
        </div>
      ) : null}

      <div className="mt-8 flex gap-3">
        <Button variant="outline" asChild>
          <Link to={listTo}>{listLabel}</Link>
        </Button>
        <Button variant="default" asChild>
          <Link to={recordTo}>{recordLabel}</Link>
        </Button>
      </div>
    </div>
  );
}
