import { Hand } from "lucide-react";
import type { KioskState } from "../api";
import { useNow } from "../hooks/use-now";
import { Screen } from "./layout";

const STEPS = [
  "On your phone, sign in to IDEN and open Security.",
  <>
    Choose <strong className="font-medium text-ink">Enrol at a kiosk</strong> to show a QR code.
  </>,
  "Touch this screen and hold the code up to the camera.",
];

/**
 * What the kiosk shows when nobody is using it: what it is for and how to start.
 * The camera is off here — a kiosk standing in a lobby films nobody who has not
 * stepped up and touched it. Touching anywhere starts a visit.
 */
export function Idle({ state, onStart }: { state: KioskState; onStart: () => void }) {
  const now = useNow();
  const footer = state.settings.notice || state.location;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Start enrolling your face"
      onClick={onStart}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onStart();
      }}
      className="h-dvh w-full focus-visible:outline-none"
    >
      <Screen
        name={state.name}
        aside={
          <time
            dateTime={now.toISOString()}
            className="font-mono text-body-md tabular-nums text-ink short:text-body-sm"
          >
            {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </time>
        }
        footer={footer}
        className="grid grid-cols-[minmax(0,1.15fr)_auto] content-center items-center gap-12 text-left portrait:grid-cols-1 portrait:justify-items-center portrait:text-center short:gap-8"
      >
        <div className="flex flex-col gap-6 short:gap-4 portrait:items-center">
          <p className="text-caption-upper uppercase text-muted-foreground">
            {now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h1 className="text-balance font-display text-display-xl text-ink short:text-display-md">
            Enrol your face for signing in
          </h1>
          <ol className="flex flex-col border-t border-hairline">
            {STEPS.map((step, index) => (
              <li
                key={index}
                className="flex items-baseline gap-5 border-b border-hairline py-3 text-title-md text-body short:gap-4 short:py-2 short:text-body-md"
              >
                <span className="w-6 shrink-0 font-display text-display-sm text-primary short:text-title-lg">
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
          <span className="inline-flex items-center gap-3 self-start rounded-lg bg-primary px-6 py-4 text-title-lg text-on-primary short:px-5 short:py-3 short:text-title-md portrait:self-center">
            <Hand aria-hidden="true" className="h-6 w-6" />
            Touch the screen to start
          </span>
        </div>
        <Viewfinder />
      </Screen>
    </div>
  );
}

/** The face oval the capture will use, with a line passing down it. Drawn, not
 * filmed: the camera is off until someone starts. */
function Viewfinder() {
  return (
    <div
      aria-hidden="true"
      className="relative aspect-[4/5] h-[min(58dvh,26rem)] overflow-hidden rounded-xl bg-surface-dark portrait:h-[min(40dvh,24rem)]"
    >
      <svg viewBox="0 0 200 250" className="absolute inset-0 h-full w-full">
        <defs>
          <clipPath id="idle-oval">
            <ellipse cx="100" cy="112" rx="58" ry="78" />
          </clipPath>
          <linearGradient id="idle-scan" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#cc785c" stopOpacity="0" />
            <stop offset="0.5" stopColor="#cc785c" stopOpacity="0.55" />
            <stop offset="1" stopColor="#cc785c" stopOpacity="0" />
          </linearGradient>
        </defs>
        <ellipse
          cx="100"
          cy="112"
          rx="74"
          ry="96"
          fill="none"
          stroke="#302e2a"
          strokeDasharray="2 6"
          strokeLinecap="round"
        />
        <g clipPath="url(#idle-oval)">
          <g
            className="animate-scan"
            style={{ transformBox: "fill-box", transformOrigin: "center" }}
          >
            <rect x="30" y="34" width="140" height="156" fill="none" />
            <rect x="30" y="102" width="140" height="20" fill="url(#idle-scan)" />
          </g>
        </g>
        <ellipse cx="100" cy="112" rx="58" ry="78" fill="none" stroke="#cc785c" strokeWidth="2" />
      </svg>
      <p className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-2 pb-4 text-caption-upper uppercase text-on-dark-soft short:pb-3">
        <span className="h-1.5 w-1.5 rounded-full bg-on-dark-soft" />
        Camera off
      </p>
    </div>
  );
}
