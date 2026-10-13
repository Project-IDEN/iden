import { cn } from "../ui/cn";
import { Logo } from "../ui/logo";
import type { ReactNode } from "react";

/** Every screen: the kiosk's name at the top, its notice at the bottom, and
 * type large enough to read from a step back. Fills the display exactly — a
 * kiosk screen never scrolls. */
export function Screen({
  name,
  aside,
  footer,
  children,
  className,
}: {
  name?: string | null;
  /** Beside the kiosk's name in the header. */
  aside?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink">
      <header className="flex shrink-0 items-center justify-between px-8 py-5 short:px-6 short:py-3">
        <span className="flex items-center gap-2 text-title-md text-ink">
          <Logo className="h-7 w-7 text-primary short:h-6 short:w-6" />
          IDEN
        </span>
        <span className="flex items-center gap-4 text-body-md text-muted-foreground">
          {name ? <span>{name}</span> : null}
          {aside}
        </span>
      </header>
      <main
        className={cn(
          "step-in mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col items-center justify-center gap-8 px-8 text-center short:gap-4 short:px-6",
          className,
        )}
      >
        {children}
      </main>
      {footer ? (
        <footer className="shrink-0 px-8 py-5 text-center text-body-md text-muted-foreground short:px-6 short:py-3 short:text-body-sm">
          {footer}
        </footer>
      ) : null}
    </div>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return (
    <h1 className="text-balance font-display text-display-lg text-ink short:text-display-sm">
      {children}
    </h1>
  );
}

export function Lede({ children }: { children: ReactNode }) {
  return <p className="max-w-2xl text-title-lg text-body short:text-title-md">{children}</p>;
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
        "inline-flex min-h-16 min-w-56 items-center justify-center gap-3 rounded-lg px-8 text-title-lg transition-colors disabled:opacity-50 short:min-h-14 short:min-w-44 short:px-6 short:text-title-md",
        variant === "primary"
          ? "bg-primary text-on-primary active:bg-primary-active"
          : "bg-surface-card text-ink active:bg-surface-cream-strong",
      )}
    >
      {children}
    </button>
  );
}
