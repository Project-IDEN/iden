import { parseScopes } from "@iden/shared";
import { useMemo } from "react";
import { useAuth } from "react-oidc-context";
import { basePath, config } from "./config";

/**
 * The scopes actually granted, read from the token.
 *
 * The token is the only honest source: `/authorize` resolves
 * `requested ∩ client.grantable ∩ effective_user_scopes` and drops the rest
 * without complaint, so what was asked for says nothing about what was given.
 */
export function useGrantedScopes(): Set<string> {
  const auth = useAuth();
  const claim = auth.user?.scope;
  return useMemo(() => parseScopes(claim), [claim]);
}

export function useHasScope(scope: string): boolean {
  return useGrantedScopes().has(scope);
}

/**
 * Ends the IDEN session as well as this app's.
 *
 * `/oauth2/logout` redirects only to a `post_logout_redirect_uri` registered on
 * the client, and the seeded dashboard client has none — so it answers 204, and
 * a top-level navigation there would leave the browser sitting where it was.
 * A credentialed fetch clears `iden_session` just as well and lets the app
 * decide where to go, which it can do because this origin is in the provider's
 * CORS allowlist.
 */
export function useSignOut(): () => Promise<void> {
  const auth = useAuth();
  return async () => {
    const idToken = auth.user?.id_token;
    const url = new URL("/oauth2/logout", config.issuer);
    if (idToken) url.searchParams.set("id_token_hint", idToken);
    try {
      await fetch(url, { credentials: "include", redirect: "manual" });
    } finally {
      await auth.removeUser();
      window.location.assign(`${basePath}/`);
    }
  };
}

/**
 * The browser session this app is signed in with, from the ID token's `sid`.
 *
 * `/entity/sessions` can only mark a row as current for a caller that sends the
 * `iden_session` cookie, and this app deliberately sends none. `sid` is how a
 * client recognises its own session without one — it is the same value, and the
 * reason it is in the token.
 */
export function useSessionId(): string | undefined {
  return useAuth().user?.profile.sid;
}

/** The signed-in person's user id. */
export function useSubject(): string | undefined {
  return useAuth().user?.profile.sub;
}

/** Carried through a sign-in, so it ends on the page that started it. */
export interface SignInState {
  returnTo?: string;
}

export function hereState(): SignInState {
  const { pathname, search } = window.location;
  // A failed callback is no page to come back to: its code is spent.
  return pathname === `${basePath}/callback` ? {} : { returnTo: pathname + search };
}

/** Starts a step-up: RFC 9470 asks for a sign-in no older than `maxAge` seconds. */
export function useStepUp(): (maxAge: number) => void {
  const auth = useAuth();
  return (maxAge: number) => {
    void auth.signinRedirect({ max_age: maxAge, state: hereState() });
  };
}
