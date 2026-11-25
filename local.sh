#!/usr/bin/env bash
# Everything IDEN needs, in Docker on localhost, on the CPU. Needs only Docker.
#
#   ./local.sh          build and start everything (safe to re-run)
#   ./local.sh down     stop it, keeping the data
#   ./local.sh reset    stop it and delete the data
set -euo pipefail
cd "$(dirname "$0")"

case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*)
    # Git Bash rewrites the container paths in the docker run calls below.
    echo "On Windows, run local.cmd instead (or this script from WSL)."
    exit 1
    ;;
esac

export IDEN_UID="$(id -u)" IDEN_GID="$(id -g)" IDEN_BIOMETRIC_ENABLED=true
compose() {
  docker compose -f deploy/docker-compose.yml \
    -f deploy/docker-compose.engine-cpu.yml \
    -f deploy/docker-compose.kiosk.yml "$@"
}

case "${1:-up}" in
  down) compose down; exit ;;
  reset) compose down -v; exit ;;
  up) ;;
  *) sed -n '2,6p' "$0"; exit 2 ;;
esac

docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker and try again."; exit 1; }

echo "==> Building images (the first run takes a while)"
compose build

mkdir -p provider/keys engine/models
if ! ls provider/keys/*.pem >/dev/null 2>&1; then
  echo "==> Generating keys"
  docker run --rm --user "$IDEN_UID:$IDEN_GID" -v "$PWD/provider/keys:/keys" \
    -e IDEN_SIGNING_KEY_DIR=/keys --entrypoint python iden-dev-provider -m scripts.gen_keys
fi

echo "==> Fetching face models (about 290 MB, once)"
docker run --rm --user "$IDEN_UID:$IDEN_GID" -v "$PWD/engine/models:/app/models" \
  --entrypoint python iden-dev-engine -m scripts.fetch_models

echo "==> Starting"
compose up -d

echo "==> Waiting for the provider"
for _ in $(seq 90); do
  curl -sf http://localhost:8000/health >/dev/null && break
  sleep 2
done
curl -sf http://localhost:8000/health >/dev/null || {
  echo "The provider did not start. See: docker compose -f deploy/docker-compose.yml logs migrate provider"
  exit 1
}

echo "==> Seeding"
compose exec provider python -m scripts.seed

cat <<'EOF'

IDEN is running.
  Dashboard     http://localhost:3000/console/
  Sign-in page  http://localhost:4000/auth/login
  Kiosk         http://localhost:8080   (pair it from Dashboard > Administration > Kiosks)
  API docs      http://localhost:8000/docs

Sign in with the administrator printed above. It is shown only on the first run;
if you lose it, run ./local.sh reset and then ./local.sh again.
EOF
