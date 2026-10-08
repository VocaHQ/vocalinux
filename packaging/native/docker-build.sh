#!/usr/bin/env bash
# Run the native package build inside the pinned Debian 12 image.
#
# Usage: docker-build.sh <path-to-wheel> <version> [output-dir]
#
# This is what CI calls and what you should call locally, so that what you
# get is what CI gets: the base image pins the pip that resolves the vendored
# wheels, and building on the host instead means shipping whatever that host
# happens to run. Debian 12 is old enough that its pip accepts every manylinux
# tag in the pinned wheels.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
IMAGE="$(awk '$1=="base-image" {print $3}' "$REPO_ROOT/packaging/native/tool_checksums.txt")"
if [ -z "$IMAGE" ]; then
    echo "No base-image pin in packaging/native/tool_checksums.txt" >&2
    exit 1
fi

# The wheel and output dir are given as host paths; the repo is mounted at
# the same place it lives, so relative arguments keep working inside. The
# container needs python3, pip, curl and tar — install-build-tools.sh adds
# them before handing off to build.sh.
exec docker run --rm \
    -v "$REPO_ROOT:$REPO_ROOT" -w "$REPO_ROOT" \
    "$IMAGE" bash packaging/native/container-build.sh "$@"
