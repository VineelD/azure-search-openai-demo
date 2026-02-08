#!/bin/sh
# Run auth_init then auth_update (app registration + redirect URIs).
# Use this for a one-off manual setup, or run auth_init.sh / auth_update.sh separately.
set -e
./scripts/auth_init.sh
./scripts/auth_update.sh
