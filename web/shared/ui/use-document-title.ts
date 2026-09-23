import { useEffect } from "react";

/**
 * Names the tab after the screen, suffixed with whose deployment this is.
 *
 * Both apps are single-page, so the `<title>` in `index.html` is written once
 * and then describes whatever the first screen happened to be for the rest of
 * the session. That is what a bookmark and a history entry are named after, and
 * it is what somebody with a dozen tabs open reads.
 *
 * Called from the component that renders the `<h1>`, so a screen cannot have a
 * heading and a tab name that disagree.
 */
export function useDocumentTitle(title: string, organization: string | null) {
  useEffect(() => {
    document.title = `${title} · ${organization ?? "IDEN"}`;
  }, [title, organization]);
}
