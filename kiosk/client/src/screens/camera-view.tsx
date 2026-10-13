import { CameraOff } from "lucide-react";
import { cn } from "../ui/cn";
import type { CameraStatus } from "../ui/use-camera";
import type { RefObject } from "react";

const CORNERS = [
  "left-0 top-0 border-l-4 border-t-4 rounded-tl-lg",
  "right-0 top-0 border-r-4 border-t-4 rounded-tr-lg",
  "left-0 bottom-0 border-l-4 border-b-4 rounded-bl-lg",
  "right-0 bottom-0 border-r-4 border-b-4 rounded-br-lg",
];

/** The live camera, mirrored as people expect, with corners to aim a phone into.
 * Sized by the screen's height, so it fits a 7" display as well as a large one. */
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
        "relative aspect-[4/3] h-[min(56dvh,27rem)] max-w-full overflow-hidden rounded-xl bg-surface-dark",
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
      <div aria-hidden="true" className="pointer-events-none absolute inset-[16%]">
        {CORNERS.map((corner) => (
          <span key={corner} className={cn("absolute h-10 w-10 border-primary", corner)} />
        ))}
      </div>
      {status === "denied" ? (
        <p className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-title-md text-on-dark">
          <CameraOff aria-hidden="true" className="h-8 w-8 text-on-dark-soft" />
          The camera is not working. Ask staff for help.
        </p>
      ) : null}
    </div>
  );
}
