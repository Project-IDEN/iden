import { Avatar, Badge, Button, IdenError, Notice } from "@iden/shared";
import { BadgeCheck, Camera } from "lucide-react";
import { useRef } from "react";
import { useApi } from "../../app/api";
import { useRemovePhoto, useUploadPhoto, type Profile } from "./api";

const HINT = "JPEG, PNG or WebP. Cropped square and resized to 512px.";

/**
 * Who you are, at the top of the page about you.
 *
 * The photo control lives here rather than among the form fields because it is
 * the one thing on this page that is not a value in a text box: it uploads,
 * and it takes effect immediately rather than on save.
 */
export function IdentityHeader({ profile }: { profile: Profile }) {
  const api = useApi();
  const upload = useUploadPhoto(api);
  const remove = useRemovePhoto(api);
  const picker = useRef<HTMLInputElement>(null);

  const busy = upload.isPending || remove.isPending;
  const problem = upload.error instanceof IdenError ? upload.error.message : null;
  const name = profile.displayName || profile.username;

  return (
    <section className="flex flex-col items-center gap-6 rounded-lg bg-surface-card p-6 text-center sm:flex-row sm:gap-8 sm:p-8 sm:text-left">
      <Avatar size="lg" name={name} src={profile.pictureUrl} />

      <div className="w-full min-w-0 sm:flex-1">
        <h2 className="text-title-lg text-ink">{name}</h2>

        <p className="mt-1 flex flex-col items-center gap-1 text-body-sm text-muted-foreground sm:flex-row sm:flex-wrap sm:gap-x-2">
          <span className="font-identity">@{profile.username}</span>
          <span aria-hidden="true" className="hidden sm:inline">
            ·
          </span>
          <span className="max-w-full truncate">{profile.email}</span>
          {profile.emailVerified ? (
            <Badge variant="secondary">
              <BadgeCheck aria-hidden="true" />
              Verified
            </Badge>
          ) : (
            <Badge variant="outline">Unverified</Badge>
          )}
        </p>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
          <Button size="sm" disabled={busy} onClick={() => picker.current?.click()}>
            <Camera aria-hidden="true" />
            {profile.pictureUrl ? "Change photo" : "Add photo"}
          </Button>
          {profile.pictureUrl ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => remove.mutate()}>
              Remove
            </Button>
          ) : null}
        </div>

        {problem ? (
          <div className="mt-3">
            <Notice title={problem} />
          </div>
        ) : (
          <p className="mt-2 text-caption text-muted-foreground">{busy ? "Working…" : HINT}</p>
        )}

        <input
          ref={picker}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            // Cleared so the same file can be chosen twice. A file input fires
            // no change event when the value it already holds is picked again,
            // which would leave a retry after a failed upload doing nothing.
            event.target.value = "";
            if (file) upload.mutate(file);
          }}
        />
      </div>
    </section>
  );
}
