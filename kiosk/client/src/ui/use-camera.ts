import { useEffect, useRef, useState } from "react";

export type CameraStatus = "starting" | "denied" | "ready";

const WIDTH = 640;
const HEIGHT = 480;

/**
 * The front camera, streaming into the returned `<video>` ref, and stopped when
 * the component unmounts.
 *
 * `prefer` picks a camera by part of its name — a kiosk with two attached says
 * which. Browsers only reveal names once a camera has been allowed, so the
 * first one opens, and is swapped for the named one when it is another.
 */
export function useCamera(prefer?: string | null) {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<CameraStatus>(() =>
    navigator.mediaDevices ? "starting" : "denied",
  );
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    let stream: MediaStream | undefined;
    let cancelled = false;
    // Absent outside a secure context: http on anything but localhost.
    if (!navigator.mediaDevices) return;

    const open = (deviceId?: string) =>
      navigator.mediaDevices.getUserMedia({
        video: {
          ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: "user" }),
          width: { ideal: WIDTH },
          height: { ideal: HEIGHT },
        },
        audio: false,
      });

    async function start() {
      let media = await open();
      const wanted = prefer?.toLowerCase();
      if (wanted && !media.getVideoTracks()[0]?.label.toLowerCase().includes(wanted)) {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const match = devices.find(
          (device) => device.kind === "videoinput" && device.label.toLowerCase().includes(wanted),
        );
        if (match) {
          media.getTracks().forEach((track) => track.stop());
          media = await open(match.deviceId);
        }
      }
      if (cancelled) return media.getTracks().forEach((track) => track.stop());
      stream = media;
      if (video.current) video.current.srcObject = media;
      setLabel(media.getVideoTracks()[0]?.label || null);
      setStatus("ready");
    }

    start().catch(() => {
      if (!cancelled) setStatus("denied");
    });
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [prefer]);

  return { video, status, label };
}
