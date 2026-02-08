# Run auth_init then auth_update (app registration + redirect URIs).
# Use this for a one-off manual setup, or run auth_init.ps1 / auth_update.ps1 separately.
$ErrorActionPreference = "Stop"
./scripts/auth_init.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
./scripts/auth_update.ps1
exit $LASTEXITCODE
