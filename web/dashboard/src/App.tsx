import { Brand, Button, ErrorState, Spinner } from "@iden/shared";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ErrorResponse } from "oidc-client-ts";
import { useAuth, type ErrorContext } from "react-oidc-context";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";
import { IdenAuthProvider } from "./app/auth";
import { basePath, config } from "./app/config";
import { Shell } from "./app/shell";
import { ProfileRoute } from "./features/account/profile";
import { SecurityRoute } from "./features/account/security";
import { ConnectionsRoute, PermissionsRoute, SessionsRoute } from "./features/account/activity";
import { RequireScope } from "./app/RequireScope";
import { UsersRoute, UserDetailRoute } from "./features/admin/users";
import { GroupsRoute, GroupDetailRoute } from "./features/admin/groups";
import { RolesRoute, RoleDetailRoute } from "./features/admin/roles";
import { ApisRoute, ApiDetailRoute } from "./features/admin/apis";
import { ClientsRoute, ClientDetailRoute } from "./features/admin/clients";
import { ClientCreateRoute } from "./features/admin/clients-new";
import { UserCreateRoute } from "./features/admin/users-new";
import { GroupCreateRoute } from "./features/admin/groups-new";
import { RoleCreateRoute } from "./features/admin/roles-new";
import { ApiCreateRoute } from "./features/admin/apis-new";
import { ProfileFieldsRoute } from "./features/admin/profile-fields";
import { ProfileFieldCreateRoute } from "./features/admin/profile-fields-new";
import { ProfileFieldEditRoute } from "./features/admin/profile-fields-edit";
import { AuditRoute } from "./features/admin/audit";
import { ApplicationsRoute, ApplicationDetailRoute } from "./features/developer/apps";
import { ApplicationCreateRoute } from "./features/developer/apps-new";

/** Every admin route is gated on the read scope its endpoints require. */
function guarded(scope: string, element: React.ReactNode) {
  return <RequireScope scope={scope}>{element}</RequireScope>;
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <Shell />,
      children: [
        { index: true, element: <Navigate to="/account/profile" replace /> },
        { path: "account/profile", element: <ProfileRoute /> },
        { path: "account/security", element: <SecurityRoute /> },
        { path: "account/sessions", element: <SessionsRoute /> },
        { path: "account/connections", element: <ConnectionsRoute /> },
        { path: "account/permissions", element: <PermissionsRoute /> },

        { path: "admin/users", element: guarded("admin:users:read", <UsersRoute />) },
        {
          path: "admin/users/new",
          element: guarded("admin:users:write", <UserCreateRoute />),
        },
        { path: "admin/users/:userId", element: guarded("admin:users:read", <UserDetailRoute />) },
        { path: "admin/groups", element: guarded("admin:groups:read", <GroupsRoute />) },
        {
          path: "admin/groups/new",
          element: guarded("admin:groups:write", <GroupCreateRoute />),
        },
        {
          path: "admin/groups/:groupId",
          element: guarded("admin:groups:read", <GroupDetailRoute />),
        },
        { path: "admin/roles", element: guarded("admin:roles:read", <RolesRoute />) },
        {
          path: "admin/roles/new",
          element: guarded("admin:roles:write", <RoleCreateRoute />),
        },
        { path: "admin/roles/:roleId", element: guarded("admin:roles:read", <RoleDetailRoute />) },
        { path: "admin/apis", element: guarded("admin:apis:read", <ApisRoute />) },
        {
          path: "admin/apis/new",
          element: guarded("admin:apis:write", <ApiCreateRoute />),
        },
        { path: "admin/apis/:apiId", element: guarded("admin:apis:read", <ApiDetailRoute />) },
        { path: "admin/clients", element: guarded("admin:clients:read", <ClientsRoute />) },
        {
          path: "admin/clients/new",
          element: guarded("admin:clients:write", <ClientCreateRoute />),
        },
        {
          path: "admin/clients/:clientId",
          element: guarded("admin:clients:read", <ClientDetailRoute />),
        },
        {
          path: "admin/profile-fields",
          element: guarded("admin:profile-fields:read", <ProfileFieldsRoute />),
        },
        {
          path: "admin/profile-fields/new",
          element: guarded("admin:profile-fields:write", <ProfileFieldCreateRoute />),
        },
        {
          path: "admin/profile-fields/:fieldId",
          element: guarded("admin:profile-fields:write", <ProfileFieldEditRoute />),
        },
        { path: "admin/audit", element: guarded("admin:audit:read", <AuditRoute />) },

        {
          path: "developer/applications",
          element: guarded("developer:clients:read", <ApplicationsRoute />),
        },
        {
          path: "developer/applications/new",
          element: guarded("developer:clients:write", <ApplicationCreateRoute />),
        },
        {
          path: "developer/applications/:applicationId",
          element: guarded("developer:clients:read", <ApplicationDetailRoute />),
        },
        { path: "*", element: <Navigate to="/account/profile" replace /> },
      ],
    },
  ],
  { basename: basePath },
);

/**
 * Sits between the OIDC provider and the router: nothing renders until there is
 * a token, and a signed-out visitor is sent straight to `/authorize` rather than
 * shown a landing page they cannot use.
 */
function RequireSignIn({ children }: { children: ReactNode }) {
  const auth = useAuth();

  if (auth.activeNavigator || auth.isLoading) {
    return <Centered>{<Spinner label="Signing you in" />}</Centered>;
  }

  const signedOut = wasSignedOut(auth.error);

  if (auth.error && !signedOut) {
    return (
      <Centered>
        <div className="max-w-md flex flex-col justify-center items-center">
          <ErrorState error={auth.error} />
          <Button className="mt-4" variant="default" onClick={() => void auth.signinRedirect()}>
            Try signing in again
          </Button>
        </div>
      </Centered>
    );
  }

  if (signedOut || !auth.isAuthenticated) {
    void auth.signinRedirect();
    return <Centered>{<Spinner label="Redirecting to sign in" />}</Centered>;
  }

  return <>{children}</>;
}

/**
 * Whether a renewal failed because the session is over rather than because
 * something broke.
 *
 * The refresh token dies with its session, so `invalid_grant` here means the
 * person was signed out somewhere else — another device, or this one revoked
 * from the sessions screen. That is not an error to show them; it is a
 * sign-out, and the honest screen is the sign-in one.
 */
function wasSignedOut(error: ErrorContext | undefined): boolean {
  return (
    error?.source === "renewSilent" &&
    error.innerError instanceof ErrorResponse &&
    error.innerError.error === "invalid_grant"
  );
}

/** The gate before the shell exists, so the lockup is the only thing naming
    where the visitor has landed. */
function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-10 px-6">
      <Brand branding={config.branding} variant="page" />
      {children}
    </div>
  );
}

export function App() {
  return (
    <IdenAuthProvider>
      <QueryClientProvider client={queryClient}>
        <RequireSignIn>
          <RouterProvider router={router} />
        </RequireSignIn>
      </QueryClientProvider>
    </IdenAuthProvider>
  );
}
