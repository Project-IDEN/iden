import type { AxiosInstance } from "axios";

// The provider's own limit, checked here first so the common mistake is caught
// before anything is created rather than after.
const MAX_BYTES = 512 * 1024;

export async function uploadLogo(api: AxiosInstance, path: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  await api.put(`${path}/logo`, body);
}

/**
 * Stores a new client's logo, if one was chosen, and says whether that worked.
 *
 * The client exists by now, so a logo that fails to upload must not lose it —
 * least of all a secret shown only once. The caller reports it where it can be
 * fixed.
 */
export async function storeLogo(api: AxiosInstance, path: string, file: File | null) {
  if (!file) return true;
  try {
    await uploadLogo(api, path, file);
    return true;
  } catch {
    return false;
  }
}

/** Router state a registration passes on when the client was created but its
 * logo was not stored, so the record's page can say so. */
export interface LogoNotice {
  logoFailed?: boolean;
}

export function problemWith(file: File): string | null {
  if (!file.type.startsWith("image/") || file.type === "image/svg+xml")
    return "Choose a PNG, JPEG or WebP image.";
  if (file.size > MAX_BYTES) return "That file is larger than 512 KB.";
  return null;
}
