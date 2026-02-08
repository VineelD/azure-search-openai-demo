# Create Microsoft Entra ID for authentication

This guide walks you through creating **Microsoft Entra ID** (formerly Azure AD) app registrations so the RAG chat app can use login and optional document-level access control.

## What you get

- **Two Entra app registrations**
  - **Server app**: Backend API; validates tokens and calls Microsoft Graph (e.g. for user/group info).
  - **Client app**: Frontend SPA; signs users in and obtains tokens to call the backend.
- **Redirect URIs** and **API scope** (`access_as_user`) configured for the app.
- **Client secret** for the server app, stored in your azd environment.

## Prerequisites

- [Azure Developer CLI (azd)](https://aka.ms/azure-dev/install) installed.
- Azure account with permission to [manage applications in Microsoft Entra ID](https://learn.microsoft.com/entra/identity/role-based-access-control/permissions-reference#cloud-application-administrator) (e.g. Cloud Application Administrator or Application Administrator).
- Logged in: `azd auth login` (and `azd auth login --tenant-id <TENANT_ID>` if using a different tenant for auth).

## Option 1: Automatic setup (recommended)

Entra apps are created automatically when you enable auth and run `azd up`.

1. **Enable authentication**
   ```bash
   azd env set AZURE_USE_AUTHENTICATION true
   ```

2. **Set the tenant used for login** (optional if same as your current tenant)
   ```bash
   azd env set AZURE_AUTH_TENANT_ID <YOUR-TENANT-ID>
   ```
   To find your tenant ID: [Azure Portal](https://portal.azure.com) → Microsoft Entra ID → Overview → **Tenant ID**.

3. **Create Entra apps and deploy**
   ```bash
   azd up
   ```
   During **preprovision**, the `auth_init` script runs and:
   - Creates the server app registration and client secret.
   - Creates the client app registration and links it to the server app.
   - Writes `AZURE_SERVER_APP_ID`, `AZURE_CLIENT_APP_ID`, and `AZURE_SERVER_APP_SECRET` into your azd environment (`.azure/<env>/.env`).

4. **(Optional) Enforce login and access control**
   - Require login and restrict search to the user’s documents:
     ```bash
     azd env set AZURE_ENFORCE_ACCESS_CONTROL true
     ```
   - Then run `azd provision` or `azd up` again so the new setting is applied.

---

## Option 2: Create Entra apps only (no full deploy)

If you only want to create the two app registrations and store their IDs in your azd environment (e.g. to configure redirect URIs or use a different deploy path):

1. **Load azd env and enable auth**
   ```bash
   azd env set AZURE_USE_AUTHENTICATION true
   azd env set AZURE_AUTH_TENANT_ID <YOUR-TENANT-ID>   # optional if same as current tenant
   ```

2. **Run the auth init script**
   - **Windows (PowerShell):**
     ```powershell
     .\scripts\auth_init.ps1
     ```
   - **Linux/macOS:**
     ```bash
     ./scripts/auth_init.sh
     ```
   Ensure the virtual environment is active (e.g. `.venv`) so the script’s dependencies are available.

3. **Check your azd environment**
   - In `.azure/<your-env>/.env` you should see:
     - `AZURE_SERVER_APP_ID`
     - `AZURE_SERVER_APP_SECRET`
     - `AZURE_CLIENT_APP_ID`
   - You can then deploy with `azd up` or `azd deploy`; redirect URIs are updated by the **auth_update** script (postprovision) using the deployed endpoint.

---

## Option 3: Manual setup in Azure Portal

To create and configure the two app registrations by hand (e.g. when you can’t run the script or need custom names/settings), follow the detailed steps in [Login and access control](login_and_acl.md#manual-setup):

- [Server app](login_and_acl.md#server-app)
- [Client app](login_and_acl.md#client-app)
- [Configure server app known client applications](login_and_acl.md#configure-server-app-known-client-applications)

Then set the resulting IDs and secret in your azd environment:

```bash
azd env set AZURE_SERVER_APP_ID <server-app-client-id>
azd env set AZURE_SERVER_APP_SECRET <server-app-secret>
azd env set AZURE_CLIENT_APP_ID <client-app-client-id>
```

---

## After Entra ID is created

- **Deploy the app**: `azd up` or `azd deploy`.
- **Run locally**: Start the app (e.g. `./app/start.ps1` or `./app/start.sh`). The client uses MSAL to sign in; redirect URIs for localhost are set by the auth scripts when you use the default endpoints.
- **Redirect URIs**: If you deploy to a custom endpoint, run the **auth_update** script (or redeploy) so the client app’s redirect URIs include your app URL. See [login_and_acl.md](login_and_acl.md) for details.

For full behavior (enforce access control, unauthenticated access, document ACLs, etc.), see [Login and access control](login_and_acl.md) and [Environment variables reference](login_and_acl.md#environment-variables-reference).
