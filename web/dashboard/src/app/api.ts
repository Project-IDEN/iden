import { createClient } from "@iden/shared";
import type { AxiosInstance } from "axios";
import { useAuth } from "react-oidc-context";
import { useMemo } from "react";
import { config } from "./config";

/**
 * The dashboard's client. No cookies: it authenticates with a bearer token and
 * has no business touching `iden_session`, which belongs to auth-ui.
 *
 * A `401` means the token is no longer accepted — the session was revoked, or
 * the account deactivated. Forgetting the user hands the page to
 * `RequireSignIn`, which sends the person to sign in and back here, instead of
 * an error whose "Try again" fails forever.
 */
export function useApi(): AxiosInstance {
  const auth = useAuth();
  const token = auth.user?.access_token;
  const { removeUser } = auth;

  return useMemo(
    () =>
      createClient({
        issuer: config.issuer,
        withCredentials: false,
        getToken: () => token,
        onUnauthorized: () => void removeUser(),
      }),
    [token, removeUser],
  );
}
