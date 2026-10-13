import { useEffect, useState } from "react";

/** Minutes and seconds until `iso`, ticking, and zero once it has passed. */
export function useCountdown(iso: string | undefined): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!iso) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [iso]);
  if (!iso) return null;
  const left = Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
}
