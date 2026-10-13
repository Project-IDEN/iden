import { useCallback, useEffect, useState } from "react";
import { getState, type KioskState } from "../api";

const POLL_MS = 10_000;

/** This kiosk's state, re-read every few seconds: settings changed in the
 * dashboard arrive through the server's heartbeat, and land here. */
export function useKioskState() {
  const [state, setState] = useState<KioskState | null>(null);
  const [reachable, setReachable] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setState(await getState());
      setReachable(true);
    } catch {
      setReachable(false);
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0);
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [refresh]);

  return { state, reachable, refresh };
}
