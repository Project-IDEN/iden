import { readBranding, readIssuer, readMailDomain } from "@iden/shared";

/**
 * The path this app is served under, without its trailing slash.
 *
 * Vite's `base` is the single source of truth; `BASE_URL` is how it reaches the
 * bundle. React Router's `basename`, the OIDC redirect URI and every
 * full-page navigation need it, and a second copy of the string is a second
 * thing to forget when it changes.
 */
export const basePath = import.meta.env.BASE_URL.replace(/\/+$/, "");

export const config = {
  issuer: readIssuer(import.meta.env.VITE_IDEN_ISSUER),
  redirectUri: `${window.location.origin}${basePath}/callback`,
  branding: readBranding({
    organization: import.meta.env.VITE_IDEN_ORG_NAME,
    logoUrl: import.meta.env.VITE_IDEN_ORG_LOGO,
  }),
  mailDomain: readMailDomain(import.meta.env.VITE_IDEN_MAIL_DOMAIN),
};
