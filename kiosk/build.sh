#!/usr/bin/env bash
# Build the kiosk image.
#
#     kiosk/build.sh ghcr.io/<you>/iden-kiosk:latest   # arm64 + amd64, pushed
#     kiosk/build.sh --local                           # this machine only, kept here
#
# The first form is what kiosks pull. It needs `docker login` to the registry
# first. On Linux it also needs two things Docker Desktop provides on its own,
# which this script sets up when they are missing: a builder that can produce
# several platforms at once, and QEMU, so an x86 machine can run arm64 build steps.
#
# The second builds for this machine's architecture and loads the image into
# the local Docker, as iden-kiosk:local unless a tag is given. Run on a
# Raspberry Pi, it is a kiosk image that needs no registry at all.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
platforms="linux/arm64,linux/amd64"
builder="iden-kiosk"

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

fail() {
  echo "build.sh: $*" >&2
  exit 1
}

local_build=false
image=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) local_build=true; shift ;;
    -h | --help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [[ -z "$image" ]] || usage; image="$1"; shift ;;
  esac
done
if $local_build; then
  image="${image:-iden-kiosk:local}"
else
  [[ -n "$image" ]] || usage
fi

command -v docker >/dev/null || fail "Docker is not installed."
docker info >/dev/null 2>&1 \
  || fail "cannot talk to Docker. Is it running, and are you in the docker group (or using sudo)?"
docker buildx version >/dev/null 2>&1 || fail "the buildx plugin is missing. Install it:
  Docker's own packages (docker-ce):   sudo apt-get install docker-buildx-plugin
  Ubuntu's packages (docker.io):        sudo apt-get install docker-buildx"

version="$(git -C "$here" describe --always --dirty 2>/dev/null || echo dev)"

if $local_build; then
  echo "==> Building $image for this machine ($(uname -m)), version $version"
  docker buildx build --load --build-arg VERSION="$version" -t "$image" "$here"
  echo
  echo "Built $image. Install it on this machine: sudo $here/deploy/install.sh --image $image ..."
  exit 0
fi

# The default builder on Docker Engine cannot produce a multi-platform image;
# a docker-container builder can.
if ! docker buildx inspect "$builder" >/dev/null 2>&1; then
  echo "==> Creating the '$builder' builder"
  docker buildx create --name "$builder" --driver docker-container --bootstrap >/dev/null
fi

# A platform the builder cannot run needs QEMU registered with the kernel.
supported="$(docker buildx inspect "$builder" --bootstrap | grep '^Platforms:')"
for platform in ${platforms//,/ }; do
  if ! grep -qw "$platform" <<<"$supported"; then
    echo "==> Registering QEMU so this $(uname -m) machine can build $platform"
    docker run --privileged --rm tonistiigi/binfmt --install "${platform#linux/}" >/dev/null
    # The builder reads the platforms it can run when it starts.
    docker buildx rm "$builder" >/dev/null
    docker buildx create --name "$builder" --driver docker-container --bootstrap >/dev/null
    supported="$(docker buildx inspect "$builder" --bootstrap | grep '^Platforms:')"
    grep -qw "$platform" <<<"$supported" || fail "QEMU is registered but the builder still cannot build $platform."
  fi
done

echo "==> Building and pushing $image for $platforms, version $version"
docker buildx build --builder "$builder" --platform "$platforms" \
  --build-arg VERSION="$version" -t "$image" --push "$here" \
  || fail "the build or the push failed. A push refused with 'denied' or 'unauthorized'
means this machine is not logged in to the registry: docker login <registry>."

echo
echo "Pushed $image. On each kiosk: sudo ./install.sh --image $image ..."
