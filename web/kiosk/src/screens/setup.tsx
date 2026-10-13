import { useCamera } from "@iden/shared";
import { Delete } from "lucide-react";
import { useState } from "react";
import { KioskError, pair, type KioskState } from "../api";
import { useQrScanner } from "../hooks/use-qr-scanner";
import { CameraView } from "./camera-view";
import { BigButton, Lede, Screen, Title } from "./layout";

const PREFIX = "iden-kiosk-pair:";
// The pairing alphabet: no 0/O, 1/I/L or U, so nothing on the screen is ambiguous.
const KEYS = "23456789ABCDEFGHJKMNPQRSTVWXYZ".split("");
const LENGTH = 8;

/** Pairing: the code from the dashboard, scanned or typed, buys this device
 * its identity. Also how a kiosk is re-paired from the maintenance screen. */
export function Setup({
  onPaired,
  onCancel,
}: {
  onPaired: (state: KioskState) => void;
  onCancel?: () => void;
}) {
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(code: string) {
    setPending(true);
    setError(null);
    try {
      onPaired(await pair(code));
    } catch (problem) {
      setError(
        problem instanceof KioskError && problem.code === "pairing_code_invalid"
          ? "That code has expired or was already used. Show a new one in the dashboard."
          : problem instanceof KioskError && problem.code === "iden_unreachable"
            ? "IDEN cannot be reached. Check the network."
            : "Pairing failed. Try again.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <Screen>
      <Title>Set up this kiosk</Title>
      <Lede>
        In the IDEN dashboard, register this kiosk under Administration → Kiosks, then show its
        pairing code here.
      </Lede>
      {typing ? (
        <Keypad pending={pending} onSubmit={(code) => void submit(code)} />
      ) : (
        <Scanner pending={pending} onCode={(code) => void submit(code)} />
      )}
      {error ? (
        <p role="alert" className="text-title-md text-error">
          {error}
        </p>
      ) : null}
      <div className="flex gap-4">
        <BigButton variant="quiet" onClick={() => setTyping(!typing)}>
          {typing ? "Scan the code instead" : "Type the code instead"}
        </BigButton>
        {onCancel ? (
          <BigButton variant="quiet" onClick={onCancel}>
            Cancel
          </BigButton>
        ) : null}
      </div>
    </Screen>
  );
}

function Scanner({ pending, onCode }: { pending: boolean; onCode: (code: string) => void }) {
  const { video, status } = useCamera();
  useQrScanner(video, !pending, (text) => {
    if (text.startsWith(PREFIX)) onCode(text.slice(PREFIX.length));
  });
  return <CameraView video={video} status={status} />;
}

function Keypad({ pending, onSubmit }: { pending: boolean; onSubmit: (code: string) => void }) {
  const [code, setCode] = useState("");
  const shown = code.length > 4 ? `${code.slice(0, 4)}-${code.slice(4)}` : code;

  return (
    <div className="flex w-full max-w-xl flex-col items-center gap-5">
      <p className="min-h-14 font-mono text-display-md tracking-[0.2em]" aria-live="polite">
        {shown || " "}
      </p>
      <div className="grid grid-cols-8 gap-2">
        {KEYS.map((key) => (
          <button
            key={key}
            type="button"
            disabled={code.length >= LENGTH}
            onClick={() => setCode(code + key)}
            className="h-14 w-14 rounded-md bg-surface-card font-mono text-title-lg active:bg-surface-cream-strong disabled:opacity-40"
          >
            {key}
          </button>
        ))}
        <button
          type="button"
          aria-label="Delete"
          onClick={() => setCode(code.slice(0, -1))}
          className="col-span-2 flex h-14 items-center justify-center rounded-md bg-surface-card active:bg-surface-cream-strong"
        >
          <Delete />
        </button>
      </div>
      <BigButton disabled={code.length !== LENGTH || pending} onClick={() => onSubmit(code)}>
        {pending ? "Pairing…" : "Pair"}
      </BigButton>
    </div>
  );
}
