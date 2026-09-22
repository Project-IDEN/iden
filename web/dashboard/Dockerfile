# Build the SPA, then serve it as static files.
#
# The workspace root is the build context: `@iden/shared` is a workspace
# dependency, so a context of `dashboard/` alone could not resolve it.
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY shared/package.json shared/
COPY dashboard/package.json dashboard/
RUN pnpm install --frozen-lockfile --filter @iden/dashboard...

COPY shared/ shared/
COPY dashboard/ dashboard/
RUN pnpm --filter @iden/dashboard build

FROM nginx:alpine
COPY --from=build /app/dashboard/dist /usr/share/nginx/html/console
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf
# The entrypoint rewrites this with the issuer filled in; shipping a copy
# means nginx still starts if it did not run.
COPY shared/nginx/security-headers.inc /etc/nginx/conf.d/security-headers.inc
COPY dashboard/entrypoint.sh /docker-entrypoint.d/40-iden-config.sh
RUN chmod +x /docker-entrypoint.d/40-iden-config.sh
EXPOSE 3000
