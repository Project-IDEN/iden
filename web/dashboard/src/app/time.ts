export function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto", style: "short" });

/**
 * "3 hr ago" rather than a timestamp. On this screen the question is *how long
 * ago*, and a date makes the reader do the subtraction themselves.
 */
export function ago(iso: string): string {
  const seconds = (Date.parse(iso) - Date.now()) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return RELATIVE.format(Math.round(seconds / size), unit);
  }
  return "just now";
}
