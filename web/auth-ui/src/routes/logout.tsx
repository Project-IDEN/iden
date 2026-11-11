import { useMutation } from "@tanstack/react-query";
import { Button, Notice } from "@iden/shared";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { signOut } from "../api";
import { AuthLayout } from "../AuthLayout";

const PASSED_ON = ["client_id", "id_token_hint", "post_logout_redirect_uri", "state"];

/**
 * Asked when a sign-out request did not come with proof that an application
 * this person uses sent it — any page can make a browser load the logout URL.
 */
export function LogoutRoute() {
  const [params] = useSearchParams();
  const [stayed, setStayed] = useState(false);

  const end = useMutation({
    mutationFn: () => {
      const form = new URLSearchParams();
      for (const name of PASSED_ON) {
        const value = params.get(name);
        if (value) form.set(name, value);
      }
      return signOut(form);
    },
    onSuccess: (target) => {
      if (target) window.location.assign(target);
    },
  });

  if (stayed) {
    return (
      <AuthLayout title="You're still signed in">
        <p className="text-body-md text-body">Nothing has changed. You can close this page.</p>
      </AuthLayout>
    );
  }

  if (end.isSuccess && end.data === null) {
    return (
      <AuthLayout title="You're signed out">
        <p className="text-body-md text-body">
          Your session has ended on this device. You can close this page.
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Sign out?"
      lede="Something asked to end your session. If it wasn't you, stay signed in."
    >
      {end.isError ? <Notice title="Couldn't sign you out">Try again.</Notice> : null}
      <div className="mt-8 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Button variant="outline" disabled={end.isPending} onClick={() => setStayed(true)}>
          Stay signed in
        </Button>
        <Button disabled={end.isPending} onClick={() => end.mutate()}>
          {end.isPending ? "Signing out…" : "Sign out"}
        </Button>
      </div>
    </AuthLayout>
  );
}
