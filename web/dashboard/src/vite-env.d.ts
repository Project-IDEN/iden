/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_IDEN_ISSUER?: string;
  readonly VITE_IDEN_ORG_NAME?: string;
  readonly VITE_IDEN_ORG_LOGO?: string;
  readonly VITE_IDEN_MAIL_DOMAIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
