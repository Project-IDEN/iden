import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge cannot tell `text-caption` (a size) from `text-muted` (a
 * colour) — both are `text-*` with a name it does not recognise, so it treats
 * them as one group and the later class silently deletes the earlier one. Every
 * type token in `tokens/theme.css` has to be named here or half the system's
 * type sizes disappear the moment a component also sets a colour.
 */
const FONT_SIZES = [
  "display-xl",
  "display-lg",
  "display-md",
  "display-sm",
  "title-lg",
  "title-md",
  "title-sm",
  "body-md",
  "body-sm",
  "caption",
  "caption-upper",
  "code",
  "button",
];

const merge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: FONT_SIZES }] } },
});

export function cn(...inputs: ClassValue[]): string {
  return merge(clsx(inputs));
}
