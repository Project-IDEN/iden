import { Button, SecretRevealOnce } from "@iden/shared";
import { Link } from "react-router";

/**
 * The last screen of a registration that produced a secret.
 *
 * It is the whole screen rather than a panel on the record, because this is the
 * only moment the secret exists in readable form and a page with somewhere else
 * to click is a page somebody clicks away from.
 *
 * `clientId` is shown only where IDEN generated it. An administrator chose
 * theirs and already knows it; a developer does not.
 */
export function SecretHandover({
  name,
  clientId,
  clientSecret,
  listTo,
  listLabel,
  recordTo,
  recordLabel,
}: {
  name: string;
  clientId?: string;
  clientSecret: string;
  listTo: string;
  listLabel: string;
  recordTo: string;
  recordLabel: string;
}) {
  return (
    <div className="max-w-xl">
      <h1 className="text-display-md">{name} registered</h1>
      <p className="mt-2 text-body-md text-body">
        Store the secret now. It is argon2-hashed on the way in and cannot be shown again — only
        rotated.
      </p>

      <div className="mt-6 flex flex-col gap-4">
        {clientId ? <SecretRevealOnce label="Client ID" secret={clientId} /> : null}
        <SecretRevealOnce label="Client secret" secret={clientSecret} />
      </div>

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
