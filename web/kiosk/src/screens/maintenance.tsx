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
    ["IDEN", state?.online ? "Reachable" : "Not reachable"],
    ["Kiosk server", reachable ? "Running" : "Not running"],
    ["Software", state?.version ?? "—"],
  ];

  return (
    <Screen>
      <Title>Maintenance</Title>
      <dl className="grid w-full max-w-lg grid-cols-2 gap-x-8 gap-y-3 text-left text-title-md">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex gap-4">
        <BigButton onClick={onPair}>Pair again</BigButton>
        <BigButton variant="quiet" onClick={onClose}>
          Close
        </BigButton>
      </div>
    </Screen>
  );
}
