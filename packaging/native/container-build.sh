#!/usr/bin/env bash
# Inside the pinned Debian 12 image: install the tools build.sh needs, then
# build both packages. Called by docker-build.sh, never directly on a host.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
# cmake, g++, make and binutils rebuild the vendored libggml-cpu from the
# pinned pywhispercpp sdist at the portable baseline in build.sh.
apt-get install -y --no-install-recommends \
    binutils ca-certificates cmake curl g++ make python3 python3-pip xz-utils

exec bash "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/build.sh" "$@"
