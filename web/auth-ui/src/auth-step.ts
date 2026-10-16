import type { AuthStep } from "./api";

/**
 * Still working, or done and on the way back to the application. Leaving the
 * page takes a moment after `complete`, and in that moment the step must not
 * offer itself again — the face step would restart the camera.
 */
export function working(mutation: { isPending: boolean; data?: AuthStep }): boolean {
  return mutation.isPending || mutation.data?.status === "complete";
}
