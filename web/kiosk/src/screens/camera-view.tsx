import { cn, type CameraStatus } from "@iden/shared";
import type { RefObject } from "react";

/** The live camera, mirrored as people expect, with a frame to aim a phone at. */
export function CameraView({
  video,
  status,
  className,
}: {
  video: RefObject<HTMLVideoElement | null>;
  status: CameraStatus;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative aspect-[4/3] w-full max-w-xl overflow-hidden rounded-lg bg-surface-dark",
        className,
      )}
    >
      <video
        ref={video}
        autoPlay
        playsInline
        muted
        className="h-full w-full -scale-x-100 object-cover"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-[18%] rounded-lg border-4 border-white/70"
      />
      {status === "denied" ? (
        <p className="absolute inset-0 flex items-center justify-center p-6 text-title-md text-on-dark">
          The camera is not working. Ask staff for help.
        </p>
      ) : null}
    </div>
  );
}
