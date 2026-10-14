/** The kiosk server on this device. It holds the credentials; this page never does. */

export interface KioskState {
  paired: boolean;
  name: string | null;
  location: string | null;
  settings: {
    idleSeconds?: number;
    inService?: boolean;
    notice?: string | null;
    cameraLabel?: string | null;
  };
  /** null until the kiosk server has asked IDEN anything. */
  online: boolean | null;
  version: string;
}

export interface EnrolmentChallenge {
  faceChallengeId: string;
  steps: string[];
  displayName: string;
  attemptsLeft: number;
}

/** IDEN's error, passed through by the kiosk server, or the server's own. */
export class KioskError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: { code?: string; message?: string; details?: object }) {
    super(body.message ?? "Something went wrong.");
    this.code = body.code ?? "error";
    this.status = status;
    this.details = (body.details ?? {}) as Record<string, unknown>;
  }
}

async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new KioskError(0, { code: "kiosk_server_down", message: "The kiosk is restarting." });
  }
  const body = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new KioskError(response.status, body ?? {});
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getState = () => send<KioskState>("/api/state");

export const pair = (code: string) => send<KioskState>("/api/pair", json({ code }));

export const reportCamera = (camera: string | null) => send<null>("/api/camera", json({ camera }));

export const startEnrolment = (ticket: string) =>
  send<EnrolmentChallenge>("/api/enrol/start", json({ ticket }));

export function enrol(ticket: string, faceChallengeId: string, frames: Blob[]) {
  const form = new FormData();
  form.append("ticket", ticket);
  form.append("faceChallengeId", faceChallengeId);
  frames.forEach((frame, index) => form.append("frames", frame, `${index}.jpg`));
  return send<{ enrolled: true; samples: number }>("/api/enrol", { method: "POST", body: form });
}
