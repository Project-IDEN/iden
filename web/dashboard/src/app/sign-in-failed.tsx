import { Brand, Button, Mark, Notice, useDocumentTitle } from "@iden/shared";
import { RotateCw } from "lucide-react";
import { config } from "./config";

/**
 * The sign-in round trip came back broken: a tab left open too long, a reload
 * partway through, a provider that could not be reached. It is drawn as the
 * sign-in card is, so it reads as a step of signing in rather than as a crash,
 * and the provider's own words are kept underneath for whoever is asked to fix
 * it.
 */
export function SignInFailed({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  useDocumentTitle("Sign-in didn't finish", config.branding.organization);

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-[26rem]">
        <Brand branding={config.branding} variant="page" className="text-ink" />

        <div className="step-in mt-6 rounded-xl border border-hairline bg-canvas p-8 shadow-[0_1px_3px_rgba(20,20,19,0.06)]">
          <p className="flex items-center gap-2 text-caption-upper uppercase text-muted-foreground">
            <Mark className="h-3 w-3 text-primary" />
            IDEN Dashboard
          </p>
          <h1 className="mt-1 text-display-sm">Sign-in didn't finish</h1>
          <p className="mt-3 text-body-sm text-body">
            Nothing is wrong with your account. This usually happens when a sign-in page was left
            open too long or reloaded partway through, and starting again fixes it.
          </p>

          <div className="mt-7 flex flex-col gap-5">
            <Notice tone="caution" title="We couldn't complete the sign-in">
              <p className="font-identity text-caption break-words text-muted-foreground">
                {detail}
              </p>
            </Notice>
            <Button variant="default" className="w-full" onClick={onRetry}>
              <RotateCw aria-hidden="true" />
              Sign in again
            </Button>
          </div>
        </div>

        <p className="mt-6 text-caption text-muted-foreground">
          If this keeps happening, contact your administrator.
        </p>
      </div>
    </div>
  );
}
