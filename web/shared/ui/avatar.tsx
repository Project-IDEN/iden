import { useState } from "react";
import { cn } from "./cn";

/**
 * A person's photo, or their initials when they have not set one.
 *
 * The fallback is the common case rather than an edge one — most people never
 * upload anything — so it is drawn as a deliberate mark instead of a broken
 * image or an empty circle.
 */
export function Avatar({
  name,
  src,
  size = "sm",
  className,
}: {
  name: string;
  src?: string | null;
  size?: "sm" | "lg";
  className?: string;
}) {
  // Which src failed, rather than a boolean, so a new photo resets the
  // fallback without an effect. A URL can 404 legitimately — an ID token names
  // whichever photo existed when it was issued, and outlives a replaced one.
  const [failed, setFailed] = useState<string | null>(null);

  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full",
        "bg-surface-cream-strong text-body-strong",
        size === "lg" ? "h-24 w-24 text-title-lg" : "h-8 w-8 text-caption",
        className,
      )}
    >
      {src && failed !== src ? (
        <img
          src={src}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setFailed(src)}
        />
      ) : (
        initials(name)
      )}
    </span>
  );
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts.at(0) ?? "";
  const last = parts.at(-1) ?? "";
  if (!first) return "?";
  const letters = parts.length === 1 ? first.slice(0, 2) : first.slice(0, 1) + last.slice(0, 1);
  return letters.toUpperCase();
}
