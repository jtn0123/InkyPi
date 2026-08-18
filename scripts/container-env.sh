#!/bin/bash
# Point the colima/lima CLIs at the VM, wherever its storage lives.
#
#   source scripts/container-env.sh
#   colima status
#
# Why this exists: the container test tier needs a Linux VM with real systemd,
# and a VM disk grows without bound as images accumulate. On a machine whose
# internal disk is tight, that belongs on external storage — but colima and
# lima only look in $HOME unless told otherwise, so their CLIs cannot find a
# relocated VM without these variables.
#
# The `docker` CLI does NOT need this: `colima start` registers a docker
# context pointing at the socket, so docker works from any shell. Only colima
# lifecycle commands (start/stop/status/delete) need the environment.
#
# Override the location by exporting INKYPI_CONTAINER_ROOT before sourcing.

# Default matches the volume this was set up on; override for another machine.
INKYPI_CONTAINER_ROOT="${INKYPI_CONTAINER_ROOT:-/Volumes/512Flash/inkypi-dev}"

export COLIMA_HOME="$INKYPI_CONTAINER_ROOT/colima"
export LIMA_HOME="$INKYPI_CONTAINER_ROOT/lima"

# Homebrew's download cache is also worth keeping off a tight internal disk.
export HOMEBREW_CACHE="$INKYPI_CONTAINER_ROOT/brew-cache"

if [ ! -d "$INKYPI_CONTAINER_ROOT" ]; then
  echo "container storage not found at $INKYPI_CONTAINER_ROOT" >&2
  echo "If this is a removable volume, mount it before starting colima." >&2
  echo "To set up elsewhere: INKYPI_CONTAINER_ROOT=/path source scripts/container-env.sh" >&2
fi
