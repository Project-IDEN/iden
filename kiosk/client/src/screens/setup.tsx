import { useCamera } from "../ui/use-camera";
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
    <Screen className="grid grid-cols-[minmax(0,1fr)_auto] content-center items-center gap-10 text-left portrait:grid-cols-1 portrait:justify-items-center portrait:text-center short:gap-6">
      <div className="flex flex-col gap-6 short:gap-4 portrait:items-center">
        <Title>Set up this kiosk</Title>
        <Lede>
          In the IDEN dashboard, register this kiosk under{" "}
          <strong className="font-medium text-ink">Administration → Kiosks</strong>, then{" "}
          {typing ? "type" : "show"} its pairing code here.
        </Lede>
        {error ? (
          <p role="alert" className="text-title-md text-error short:text-body-md">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-4 short:gap-3 portrait:justify-center">
          <BigButton variant="quiet" onClick={() => setTyping(!typing)}>
            {typing ? "Scan the code instead" : "Type the code instead"}
          </BigButton>
          {onCancel ? (
            <BigButton variant="quiet" onClick={onCancel}>
              Cancel
            </BigButton>
          ) : null}
        </div>
      </div>
      {typing ? (
        <Keypad pending={pending} onSubmit={(code) => void submit(code)} />
      ) : (
        <Scanner pending={pending} onCode={(code) => void submit(code)} />
      )}
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

/** Eight keys to a row, the code shown as it is printed in the dashboard. */
function Keypad({ pending, onSubmit }: { pending: boolean; onSubmit: (code: string) => void }) {
  const [code, setCode] = useState("");
  const key =
    "h-14 w-14 rounded-md bg-surface-card font-mono text-title-lg text-ink active:bg-surface-cream-strong disabled:opacity-40 short:h-11 short:w-11 short:text-title-md";

  return (
    <div className="flex flex-col items-center gap-5 short:gap-3">
      <p
        aria-live="polite"
        aria-label={`Code: ${code || "empty"}`}
        className="flex items-center gap-2 font-mono text-display-sm text-ink short:text-title-lg"
      >
        {Array.from({ length: LENGTH }, (_, index) => (
          <span key={index} className="contents">
            {index === 4 ? <span className="text-muted-soft">-</span> : null}
            <span
              className={`flex h-12 w-9 items-center justify-center border-b-2 short:h-9 short:w-7 ${
                index === code.length ? "border-primary" : "border-hairline"
              }`}
            >
              {code[index] ?? ""}
            </span>
          </span>
        ))}
      </p>
      <div className="grid grid-cols-8 gap-2">
        {KEYS.map((letter) => (
          <button
            key={letter}
            type="button"
            disabled={code.length >= LENGTH}
            onClick={() => setCode(code + letter)}
            className={key}
          >
            {letter}
          </button>
        ))}
        <button
          type="button"
          aria-label="Delete"
          onClick={() => setCode(code.slice(0, -1))}
          className="col-span-2 flex h-14 items-center justify-center rounded-md bg-surface-card active:bg-surface-cream-strong short:h-11"
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
