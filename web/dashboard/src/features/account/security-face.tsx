import { Button, ConfirmDialog, IdenError, StatusDot } from "@iden/shared";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { useApi } from "../../app/api";
import { useCountdown } from "../../app/countdown";
import { useHasScope } from "../../app/session";
import { useFaceStatus, type EnrolmentTicket } from "./api";
import { PendingSetting, Problem, Setting } from "./security-setting";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

/**
 * A face is enrolled at a kiosk, never here. What this page offers is the
 * ticket that lets a kiosk do it — a QR code naming you, good once and for a
 * few minutes — and the way to remove a face that is on file.
 *
 * Absent when the deployment has no biometric module: the token then carries
 * no `entity:face:read`.
 */
export function FaceSetting() {
  const api = useApi();
  const visible = useHasScope("entity:face:read");
  const [ticket, setTicket] = useState<(EnrolmentTicket & { issuedAt: number }) | null>(null);
  const status = useFaceStatus(api, visible, ticket !== null);
  const queryClient = useQueryClient();
  const [removing, setRemoving] = useState(false);
  const remaining = useCountdown(ticket?.expiresAt);

  const create = useMutation({
    mutationFn: async () => (await api.post<EnrolmentTicket>("/entity/face/ticket")).data,
    onSuccess: (issued) => setTicket({ ...issued, issuedAt: Date.now() }),
  });

  const remove = useMutation({
    mutationFn: () => api.delete("/entity/face"),
    onSuccess: () => {
      setRemoving(false);
      void queryClient.invalidateQueries({ queryKey: ["face"] });
    },
    onError: () => setRemoving(false),
  });

  if (!visible) return null;

  if (!status.data) {
    return (
      <PendingSetting
        title="Face"
        failed={status.isError}
        failure="Could not check whether a face is enrolled."
        onRetry={() => void status.refetch()}
      />
    );
  }

  const problem =
    create.error instanceof IdenError
      ? create.error
      : remove.error instanceof IdenError
        ? remove.error
        : null;
  const face = status.data;
  // The kiosk has used the ticket, so the code has done its job. Set during
  // render, React's pattern for state derived from a query.
  if (ticket && face.enrolledAt && Date.parse(face.enrolledAt) >= ticket.issuedAt - 5000) {
    setTicket(null);
  }

  return (
    <Setting
      title="Face"
      status={
        face.enrolled && face.enrolledAt ? (
          <span className="flex flex-wrap items-center gap-x-2">
            <StatusDot tone="success" label="On" />
            Enrolled at {face.enrolledBy} on {formatDate(face.enrolledAt)}. Offered when an
            application asks for a second factor.
          </span>
        ) : (
          <span className="flex flex-wrap items-center gap-x-2">
            <StatusDot tone="muted" label="Off" />
            Enrol your face at a kiosk to use it as a second factor.
          </span>
        )
      }
      action={
        ticket ? (
          <Button size="sm" variant="ghost" onClick={() => setTicket(null)}>
            Done
          </Button>
        ) : (
          <>
            <Button size="sm" disabled={create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "Preparing…" : face.enrolled ? "Enrol again" : "Enrol at a kiosk"}
            </Button>
            {face.enrolled ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => setRemoving(true)}>
                  Remove
                </Button>
                <ConfirmDialog
                  open={removing}
                  onOpenChange={setRemoving}
                  title="Remove your face?"
                  body="Face will no longer be offered when you sign in. You can enrol again at a kiosk."
                  confirmLabel="Remove face"
                  pending={remove.isPending}
                  onConfirm={() => remove.mutate()}
                />
              </>
            ) : null}
          </>
        )
      }
    >
      <Problem problem={problem} />

      {ticket ? (
        <div className="flex flex-col gap-4">
          <p className="text-body-sm text-body">
            Show this code to the kiosk camera. It names you to the kiosk, works once, and only for
            a few minutes. {face.enrolled ? "Enrolling replaces the face on file." : null}
          </p>
          {remaining === "0:00" ? (
            <div className="flex flex-col items-start gap-3">
              <p className="text-body-sm text-error">This code has expired.</p>
              <Button size="sm" onClick={() => create.mutate()}>
                Get a new code
              </Button>
            </div>
          ) : (
            <>
              <div className="w-fit rounded-lg bg-canvas p-4 ring-1 ring-hairline">
                <QRCodeSVG value={ticket.ticket} size={200} bgColor="#faf9f5" fgColor="#141413" />
              </div>
              <p className="text-caption text-muted-foreground" aria-live="polite">
                Expires in {remaining}
              </p>
            </>
          )}
        </div>
      ) : null}
    </Setting>
  );
}
