import { useRef, useState } from "react";
import { useKioskState } from "./hooks/use-kiosk-state";
import { Enrolment } from "./screens/enrol";
import { Maintenance } from "./screens/maintenance";
import { Setup } from "./screens/setup";
import { Unavailable } from "./screens/status";

const MAINTENANCE_HOLD_MS = 5000;

export function App() {
  const { state, reachable, refresh } = useKioskState();
  const [maintenance, setMaintenance] = useState<"closed" | "open" | "pairing">("closed");
  const hold = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Staff reach maintenance with a long press where nobody rests a finger.
  const corner = (
    <div
      aria-hidden="true"
      className="fixed left-0 top-0 z-40 h-20 w-20"
      onPointerDown={() => {
        hold.current = setTimeout(() => setMaintenance("open"), MAINTENANCE_HOLD_MS);
      }}
      onPointerUp={() => clearTimeout(hold.current)}
      onPointerLeave={() => clearTimeout(hold.current)}
    />
  );

  const paired = () => {
    setMaintenance("closed");
    void refresh();
  };

  let screen;
  if (maintenance === "pairing") {
    screen = <Setup onPaired={paired} onCancel={() => setMaintenance("open")} />;
  } else if (maintenance === "open") {
    screen = (
      <Maintenance
        state={state}
        reachable={reachable}
        onPair={() => setMaintenance("pairing")}
        onClose={() => setMaintenance("closed")}
      />
    );
  } else if (!reachable) {
    screen = <Unavailable title="Starting up…">This kiosk will be ready in a moment.</Unavailable>;
  } else if (state === null) {
    screen = <Unavailable title="Starting up…">One moment.</Unavailable>;
  } else if (!state.paired) {
    screen = <Setup onPaired={paired} />;
  } else if (!state.online) {
    screen = (
      <Unavailable name={state.name} title="Out of order">
        This kiosk cannot reach IDEN right now. Try again later, or ask staff for help.
      </Unavailable>
    );
  } else if (state.settings.inService === false) {
    screen = (
      <Unavailable name={state.name} title="Out of service">
        {state.settings.notice || "This kiosk is not enrolling faces right now."}
      </Unavailable>
    );
  } else {
    screen = <Enrolment state={state} />;
  }

  return (
    <>
      {corner}
      {screen}
    </>
  );
}
