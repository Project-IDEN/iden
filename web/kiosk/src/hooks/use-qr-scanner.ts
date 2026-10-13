import jsQR from "jsqr";
import { useEffect, useRef, type RefObject } from "react";

const SCAN_MS = 250;
// Decoding a quarter of the pixels is four times faster and still reads a
// phone's QR code held at arm's length.
const SCALE = 0.5;

/**
 * Reads QR codes from a playing `<video>`, calling `onCode` with each new one.
 * Chromium on Linux has no `BarcodeDetector`, so the decoding is jsQR's.
 */
export function useQrScanner(
  video: RefObject<HTMLVideoElement | null>,
  active: boolean,
  onCode: (text: string) => void,
) {
  const handler = useRef(onCode);
  useEffect(() => {
    handler.current = onCode;
  }, [onCode]);

  useEffect(() => {
    if (!active) return;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { willReadFrequently: true });
    let last = "";

    const timer = setInterval(() => {
      const source = video.current;
      if (!context || !source || source.readyState < 2) return;
      canvas.width = Math.round(source.videoWidth * SCALE);
      canvas.height = Math.round(source.videoHeight * SCALE);
      context.drawImage(source, 0, 0, canvas.width, canvas.height);
      const image = context.getImageData(0, 0, canvas.width, canvas.height);
      const code = jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
      if (code?.data && code.data !== last) {
        last = code.data;
        handler.current(code.data);
      }
    }, SCAN_MS);
    return () => clearInterval(timer);
  }, [video, active]);
}
