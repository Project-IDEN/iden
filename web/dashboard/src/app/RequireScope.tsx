import { EmptyState } from "@iden/shared";
import type { ReactNode } from "react";
import { useGrantedScopes } from "./session";

/**
 * Guards a route the token does not carry the scope for — every one of them,
 * when given a list.
 *
 * The nav already hides these, so reaching one means a typed URL or a stale
 * bookmark — which deserves an explanation, not a redirect that looks like the
 * page does not exist.
 */
export function RequireScope({
  scope,
  children,
}: {
  scope: string | readonly string[];
  children: ReactNode;
}) {
  const granted = useGrantedScopes();
  const required = typeof scope === "string" ? [scope] : scope;
  if (required.every((value) => granted.has(value))) return <>{children}</>;

  return (
    <EmptyState
      title="You don't have access to this"
      body="Your permissions don't include this section. An administrator can grant it through a role or a group."
    />
  );
}
