/** A wait, said the way a person would: "40 seconds", "15 minutes", "an hour". */
export function duration(seconds: number): string {
  if (seconds < 90) return `${Math.max(Math.round(seconds), 1)} seconds`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 90) return minutes === 1 ? "a minute" : `${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "an hour" : `${hours} hours`;
}
