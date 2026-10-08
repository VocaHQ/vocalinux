#!/usr/bin/env bash
# Inside the pinned Debian 12 image: install the tools build.sh needs, then
# build both packages. Called by docker-build.sh, never directly on a host.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl python3 python3-pip xz-utils

exec bash "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/build.sh" "$@"
