# OAuth 2.0 Authentication for ServiceNow Instances

This guide covers how to set up OAuth 2.0 authentication between the Tech Assessment Hub and your ServiceNow instances. OAuth provides token-based authentication, which is more secure than sending basic auth credentials with every API request.

---

## Prerequisites

- Admin access to your ServiceNow instance
- The **OAuth 2.0** plugin must be active (`com.snc.platform.security.oauth`)
- A ServiceNow service account with appropriate read access (same as basic auth)

## Step 1: Verify OAuth is Enabled in ServiceNow

1. Log in to your ServiceNow instance as an admin.
2. Navigate to **System Properties > All Properties**.
3. Search for `com.snc.platform.security.oauth.is.active`.
4. Ensure the value is `true`. If it is not, set it to `true` and save.

> If the property does not exist, you may need to activate the OAuth plugin first:
> Navigate to **System Definition > Plugins**, search for "OAuth 2.0", and activate it.

## Step 2: Create an OAuth Application in ServiceNow

1. Navigate to **System OAuth > Application Registry**.
2. Click **New**.
3. Select **"Create an OAuth API endpoint for external clients"**.
4. Fill in the following fields:

| Field | Value |
|-------|-------|
| **Name** | `Tech Assessment Hub` (or any descriptive name) |
| **Client ID** | Auto-generated (copy this after saving) |
| **Client Secret** | Auto-generated (copy this after saving) |
| **Redirect URL** | Leave blank (not needed for password grant) |
| **Token Lifespan** | Default is 1800 seconds (30 minutes) -- adjust if needed |
| **Refresh Token Lifespan** | Default is 8640000 seconds (100 days) |
| **Active** | Checked |

5. Click **Submit**.
6. Re-open the record to copy the **Client ID** and **Client Secret**.

> **Important:** The Client Secret is only fully visible when you first create the record. Make sure to copy it before navigating away.

## Step 3: Configure OAuth in the Tech Assessment Hub

### Adding a New Instance with OAuth

1. Go to the **Instances** page in the Tech Assessment Hub.
2. Click **Add Instance**.
3. Fill in the standard fields:
   - **Instance Name** (e.g., "PROD", "DEV")
   - **Company** (optional)
   - **Instance URL** (e.g., `mycompany.service-now.com`)
4. Under **Authentication Method**, select **OAuth 2.0**.
5. Fill in the **Username** and **Password** for the ServiceNow service account.
   - These are still required for the OAuth Password Grant flow.
6. Fill in the **OAuth Application Credentials**:
   - **Client ID** -- from the Application Registry record in Step 2
   - **Client Secret** -- from the Application Registry record in Step 2
7. Click **Save Instance**.

The app will automatically test the connection using OAuth and, if successful, kick off the standard data pulls.

### Switching an Existing Instance to OAuth

1. Go to the **Instances** page.
2. Click **Edit** on the instance you want to update.
3. Change the **Authentication Method** from "Basic Auth" to "OAuth 2.0".
4. Enter the **Client ID** and **Client Secret**.
5. Click **Save Instance**.
6. Click **Test** to verify the OAuth connection works.

> When switching auth types, cached OAuth tokens are cleared and a fresh token exchange is performed on the next connection.

## How It Works

### Authentication Flow

The app uses the **OAuth 2.0 Resource Owner Password Credentials** (Password Grant) flow:

```
Tech Assessment Hub                    ServiceNow
        |                                   |
        |  POST /oauth_token.do             |
        |  grant_type=password              |
        |  client_id=xxx                    |
        |  client_secret=xxx               |
        |  username=xxx                     |
        |  password=xxx                     |
        |---------------------------------->|
        |                                   |
        |  { access_token, refresh_token,   |
        |    expires_in: 1800 }             |
        |<----------------------------------|
        |                                   |
        |  GET /api/now/table/...           |
        |  Authorization: Bearer <token>    |
        |---------------------------------->|
        |                                   |
```

### Token Lifecycle

- **Access tokens** expire after 30 minutes (default, configurable in ServiceNow).
- **Refresh tokens** expire after 100 days (default).
- The app automatically refreshes expired access tokens using the refresh token.
- If the refresh token also expires, the app performs a full re-authentication.
- Tokens are cached (encrypted) on the instance record to survive app restarts.

### Automatic Token Refresh

If an API call returns a 401 (Unauthorized) while using OAuth, the app will:

1. Attempt to refresh the access token using the refresh token.
2. If refresh fails, perform a full password grant exchange.
3. Retry the original API call with the new token.

This happens transparently -- no manual intervention is needed.

## Security Considerations

- **Client Secret** is encrypted at rest using the same Fernet encryption as passwords.
- **Access and refresh tokens** are also encrypted at rest.
- **OAuth is preferred** over basic auth because credentials are exchanged once for a token, rather than sent with every API request.
- Tokens have a limited lifespan, reducing the window of exposure if intercepted.

## Troubleshooting

### "OAuth token exchange failed (HTTP 401): Bad credentials"

- Verify the **Client ID** and **Client Secret** match the Application Registry record in ServiceNow.
- Ensure the OAuth application is **Active** in ServiceNow.
- Check that the **username** and **password** are correct.

### "OAuth token exchange failed (HTTP 400)"

- The OAuth plugin may not be active. Check `com.snc.platform.security.oauth.is.active`.
- The Application Registry record may be inactive or deleted.

### "Could not connect to oauth_token.do"

- Verify the instance URL is correct and reachable.
- Check network/firewall rules allow outbound HTTPS to the ServiceNow instance.

### Token refresh keeps failing

- The refresh token may have expired (default: 100 days). Edit the instance and re-save with the same credentials to force a fresh token exchange.
- In ServiceNow, check the Application Registry record's **Refresh Token Lifespan** setting.

### Everything worked before but stopped

- The service account password may have been changed in ServiceNow. Update it in the instance settings.
- The OAuth application may have been deactivated in ServiceNow. Re-activate it.
- ServiceNow may have rotated the Client Secret (rare). Check and update if needed.

## Comparison: Basic Auth vs OAuth

| Aspect | Basic Auth | OAuth 2.0 |
|--------|-----------|-----------|
| **Credentials per request** | Username + password (Base64) | Bearer token only |
| **Token expiry** | N/A (credentials always valid) | 30 min access, 100 day refresh |
| **Setup complexity** | None | Requires Application Registry config |
| **Security** | Credentials sent every request | Credentials exchanged once for token |
| **Revocation** | Change password | Revoke token or deactivate app |
| **Compatibility** | All ServiceNow versions | Requires OAuth plugin |

## ServiceNow Version Compatibility

- **Password Grant** (used by this app): Supported on all modern ServiceNow releases with the OAuth plugin active.
- **Client Credentials Grant** (not currently used): Only available starting with the **Washington DC** release.
