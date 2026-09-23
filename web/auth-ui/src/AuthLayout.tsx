import { Brand, Mark, useDocumentTitle } from "@iden/shared";
import type { ReactNode } from "react";
import { branding } from "./branding";

/**
 * Every screen in this app is one card on the cream canvas. The card is narrow
 * on purpose — this is the one surface where nothing competes for attention.
 */
export function AuthLayout({
  eyebrow,
  title,
  lede,
  children,
  footer,
  step,
}: {
  eyebrow?: string;
  title: string;
  lede?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Changing this replays the entrance, marking a step within the same flow. */
  step?: string;
}) {
  useDocumentTitle(title, branding.organization);

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-[26rem]">
        <Brand branding={branding} variant="page" className="text-ink" />

        <div
          key={step}
          className="step-in mt-6 rounded-xl border border-hairline bg-canvas p-8 shadow-[0_1px_3px_rgba(20,20,19,0.06)]"
        >
          {eyebrow ? (
            <p className="flex items-center gap-2 text-caption-upper uppercase text-muted-foreground">
              <Mark className="h-3 w-3 text-primary" />
              {eyebrow}
            </p>
          ) : null}
          <h1 className="mt-1 text-display-sm">{title}</h1>
          {lede ? <div className="mt-3 text-body-sm text-body">{lede}</div> : null}
          <div className="mt-7">{children}</div>
        </div>

        {footer ? <div className="mt-6 text-caption text-muted-foreground">{footer}</div> : null}
      </div>
    </div>
  );
}
