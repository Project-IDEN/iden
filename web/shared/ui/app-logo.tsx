import { useState } from "react";
import { cn } from "./cn";

/**
 * An application's logo, or its initials when it has none.
 *
 * A rounded square rather than the circle a person's `Avatar` is, so an app and
 * a person never read as the same kind of thing. The image is contained, not
 * cropped: logos arrive in their own proportions, and a wordmark cut to a
 * square loses its words.
 */
export function AppLogo({
  name,
  src,
  size = "sm",
  className,
}: {
  name: string;
  src?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);

  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden border border-hairline",
        "bg-surface-cream-strong text-body-strong",
        size === "lg" && "h-20 w-20 rounded-xl p-2 text-title-md",
        size === "md" && "h-14 w-14 rounded-lg p-1.5 text-title-sm",
        size === "sm" && "h-8 w-8 rounded-md p-0.5 text-caption",
        src && failed !== src && "bg-canvas",
        className,
      )}
    >
      {src && failed !== src ? (
        <img
          src={src}
          alt=""
          className="h-full w-full object-contain"
          onError={() => setFailed(src)}
        />
      ) : (
        initials(name)
      )}
    </span>
  );
}

function initials(name: string) {
  const [first = "", second = ""] = name.trim().split(/\s+/);
  if (!first) return "?";
  return (second ? first.slice(0, 1) + second.slice(0, 1) : first.slice(0, 2)).toUpperCase();
}
