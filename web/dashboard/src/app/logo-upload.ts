import type { AxiosInstance } from "axios";

// The provider's own limit, checked here first so the common mistake is caught
// before anything is created rather than after.
const MAX_BYTES = 512 * 1024;

export async function uploadLogo(api: AxiosInstance, path: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  await api.put(`${path}/logo`, body);
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
