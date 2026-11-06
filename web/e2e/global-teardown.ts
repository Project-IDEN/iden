/**
 * Deletes every account and client the suite created — the ones setup made
 * and the ones tests made through the dashboard — found by the `e2e-` prefix.
 */
import { PREFIX, adminToken, api } from "./support/iden";

interface Page<T> {
  items: T[];
}

export default async function globalTeardown() {
  const token = await adminToken();

  const users = await api<Page<{ id: string; username: string }>>(
    token,
    "GET",
    `/admin/users?search=${PREFIX}&limit=200`,
  );
  for (const user of users.items.filter((u) => u.username.startsWith(PREFIX))) {
    await api(token, "DELETE", `/admin/users/${user.id}`);
  }

  const clients = await api<Page<{ id: string; clientId: string }>>(
    token,
    "GET",
    "/admin/clients?limit=200",
  );
  for (const client of clients.items.filter((c) => c.clientId.startsWith(PREFIX))) {
    await api(token, "DELETE", `/admin/clients/${client.id}`);
  }
}
