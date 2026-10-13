import { Brand, cn } from "@iden/shared";
import type { ReactNode } from "react";

/** Every screen: the kiosk's name at the top, its notice at the bottom, and
 * type large enough to read from a step back. */
export function Screen({
  name,
  footer,
  children,
  className,
}: {
  name?: string | null;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas text-ink">
      <header className="flex items-center justify-between px-8 py-5">
        <Brand branding={{ organization: null, logoUrl: null }} />
        {name ? <span className="text-body-md text-muted-foreground">{name}</span> : null}
      </header>
      <main
        className={cn(
          "mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-8 px-8 text-center",
          className,
        )}
      >
        {children}
      </main>
      {footer ? (
        <footer className="px-8 py-5 text-center text-body-md text-muted-foreground">
          {footer}
        </footer>
      ) : null}
    </div>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return <h1 className="font-display text-display-md text-ink">{children}</h1>;
}

export function Lede({ children }: { children: ReactNode }) {
  return <p className="max-w-2xl text-title-lg text-body">{children}</p>;
}

/** A finger-sized button. */
export function BigButton({
  children,
  onClick,
  variant = "primary",
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  variant?: "primary" | "quiet";
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "min-h-16 min-w-56 rounded-lg px-8 text-title-lg transition-colors disabled:opacity-50",
        variant === "primary"
          ? "bg-primary text-on-primary active:bg-primary-active"
          : "bg-surface-card text-ink active:bg-surface-cream-strong",
      )}
    >
      {children}
    </button>
  );
}
