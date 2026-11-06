/**
 * Creates what the suite needs through the admin API, as an administrator
 * would: four member accounts with known passwords and a third-party client
 * that must ask for consent. Their ids land in .state.json for the tests and
 * for teardown.
 */
import { randomBytes } from "node:crypto";
import {
  PREFIX,
  THIRD_PARTY_REDIRECT,
  adminCredentials,
  adminToken,
  api,
  saveState,
  type Account,
} from "./support/iden";

interface Page<T> {
  items: T[];
}

export default async function globalSetup() {
  const token = await adminToken();
  const roles = await api<Page<{ id: string; name: string }>>(
    token,
    "GET",
    "/admin/roles?limit=200",
  );
  const member = roles.items.find((role) => role.name === "member");
  const memberRole = member?.id;
  if (!memberRole) throw new Error("the seeded `member` role is missing; run scripts.seed");

  const run = randomBytes(3).toString("hex");

  async function account(kind: string): Promise<Account> {
    const local = `${PREFIX}${kind}-${run}`;
    const password = `E2e-${randomBytes(9).toString("base64url")}`;
    const displayName = `E2E ${kind[0]?.toUpperCase()}${kind.slice(1)} ${run}`;
    const created = await api<{ id: string; email: string }>(token, "POST", "/admin/users", {
      emailLocalPart: local,
      username: local,
      displayName,
      password,
      roleIds: [memberRole],
    });
    return { id: created.id, email: created.email, password, displayName };
  }

  const thirdParty = await api<{ id: string; clientId: string }>(token, "POST", "/admin/clients", {
    clientId: `${PREFIX}library-${run}`,
    name: `E2E Library ${run}`,
    clientType: "public",
    allowedGrants: ["authorization_code"],
    redirectUris: [THIRD_PARTY_REDIRECT],
    skipConsent: false,
  });

  saveState({
    admin: adminCredentials(),
    member: await account("member"),
    totp: await account("totp"),
    sessions: await account("sessions"),
    consent: await account("consent"),
    thirdParty: { id: thirdParty.id, clientId: thirdParty.clientId },
  });
}
