/**
 * Before any test: a dedicated test user (never the operator's account), a
 * kiosk registration to pair, and the camera files that do not depend on a
 * ticket — a blank frame, and a face darkened to 15 % brightness. All through
 * the admin API and ffmpeg; nothing is written to the database by hand.
 */
import { randomBytes } from "node:crypto";
import { mkdirSync, rmSync } from "node:fs";
import { MEDIA, RESULTS, adminToken, api, saveState } from "./support/iden";
import { FACE, blankPng, darkened, stillY4m } from "./support/media";

export default async function globalSetup() {
  rmSync(MEDIA, { recursive: true, force: true });
  mkdirSync(`${RESULTS}screenshots`, { recursive: true });

  stillY4m(blankPng(), "blank.y4m");
  darkened(FACE, 0.15, "face-dark-15.png");

  const token = await adminToken();
  const roles = await api<{ items: { id: string; name: string }[] }>(token, "GET", "/admin/roles?limit=200");
  const member = roles.items.find((role) => role.name === "member")?.id;
  if (!member) throw new Error("The seeded `member` role is missing; run scripts.seed.");

  const run = randomBytes(3).toString("hex");
  const password = `M07-${randomBytes(12).toString("base64url")}`;
  const displayName = `M07 Kiosk Tester ${run}`;
  const user = await api<{ id: string; email: string }>(token, "POST", "/admin/users", {
    emailLocalPart: `m07-kiosk-${run}`,
    username: `m07-kiosk-${run}`,
    displayName,
    password,
    roleIds: [member],
  });

  const kiosk = await api<{ id: string; clientId: string; name: string }>(token, "POST", "/admin/kiosks", {
    name: `M07 Test Kiosk ${run}`,
    location: "TDS laptop",
  });

  saveState({
    kiosk: { id: kiosk.id, clientId: kiosk.clientId, name: kiosk.name },
    user: { id: user.id, email: user.email, password, displayName },
  });
}
