import { DASHBOARD_SCOPE } from "@iden/shared";
import type { ReactNode } from "react";
import { AuthProvider, type AuthProviderProps } from "react-oidc-context";
import { WebStorageStateStore } from "oidc-client-ts";
import { basePath, config } from "./config";
import type { SignInState } from "./session";

const oidcConfig: AuthProviderProps = {
  authority: config.issuer,
  client_id: "dashboard",
  redirect_uri: config.redirectUri,
  response_type: "code",
  scope: DASHBOARD_SCOPE,
  // Refresh tokens rotate on every use, so the library must hold the current
  // one; sessionStorage keeps it out of other tabs and out of disk.
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  automaticSilentRenew: true,
  // The code lands on /callback; leaving it in the address bar invites a reload,
  // and codes are single-use. Back to the page that sent the person to sign in.
  onSigninCallback: (user) => {
    const { returnTo } = (user?.state ?? {}) as SignInState;
    window.history.replaceState({}, "", returnTo ?? `${basePath}/`);
  },
};

export function IdenAuthProvider({ children }: { children: ReactNode }) {
  return <AuthProvider {...oidcConfig}>{children}</AuthProvider>;
}
