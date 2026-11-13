import type { KioskState } from "../api";
import { BigButton, Screen, Title } from "./layout";

/** For staff: what this kiosk is and whether it can reach IDEN. Opened by a
 * long press on the top-left corner. */
export function Maintenance({
  state,
  reachable,
  onPair,
  onClose,
}: {
  state: KioskState | null;
  reachable: boolean;
  onPair: () => void;
  onClose: () => void;
}) {
  const rows: [string, string][] = [
    ["Kiosk", state?.name ?? "Not paired"],
    ["Location", state?.location ?? "—"],
    [
      "IDEN",
      state?.online == null ? "Not checked yet" : state.online ? "Reachable" : "Not reachable",
    ],
    ["Kiosk server", reachable ? "Running" : "Not running"],
    ["Software", state?.version ?? "—"],
  ];

  return (
    <Screen>
      <Title>Maintenance</Title>
      <dl className="w-full max-w-lg rounded-xl bg-surface-card px-6 py-2 text-left text-title-md short:text-body-md">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex justify-between gap-8 border-b border-hairline py-3 last:border-b-0 short:py-2"
          >
            <dt className="shrink-0 text-muted-foreground">{label}</dt>
            <dd className="min-w-0 break-words text-right text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap justify-center gap-4">
        <BigButton onClick={onPair}>Pair again</BigButton>
        <BigButton variant="quiet" onClick={onClose}>
          Close
        </BigButton>
      </div>
    </Screen>
  );
}
