import { useEffect, useRef } from "react";

/** Calls `onIdle` after `seconds` without a touch, while `active`. */
export function useIdle(active: boolean, seconds: number, onIdle: () => void) {
  const handler = useRef(onIdle);
  useEffect(() => {
    handler.current = onIdle;
  }, [onIdle]);

  useEffect(() => {
    if (!active) return;
    let timer = setTimeout(() => handler.current(), seconds * 1000);
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(() => handler.current(), seconds * 1000);
    };
    window.addEventListener("pointerdown", reset);
    window.addEventListener("keydown", reset);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pointerdown", reset);
      window.removeEventListener("keydown", reset);
    };
  }, [active, seconds]);
}
