# Sign in with Google — 5-minute setup

Vigil can show a **"Sign in with Google"** button on its login page, so you and
your staff sign in with Google accounts instead of remembering another password.

Google requires every app that uses this to have its own (free) **client ID**.
You create it once; it takes about 5 minutes.

## 1. Create the client ID

1. Go to <https://console.cloud.google.com/apis/credentials>
   (sign in with your own Google account).
2. If asked, create a project — call it `Vigil` and accept the defaults.
3. If you see **"Configure consent screen"**, do that first:
   - User type: **External** → Create
   - App name `Vigil`, pick your email for the two email fields → Save through
     the remaining steps (you can leave everything else empty).
4. Back on **Credentials**, click **+ Create credentials → OAuth client ID**.
5. Application type: **Web application**. Name: `Vigil`.
6. Under **Authorized JavaScript origins**, add every address you open Vigil at:
   - `http://localhost:8000`
   - `http://127.0.0.1:8000`
   - If you open the dashboard from other machines on your network, also add
     that address, e.g. `http://192.168.1.20:8000`
   - If you use Vigil-Public (a tunnel), add its `https://…` address too.
7. Click **Create** and copy the **Client ID** — it looks like
   `1234567890-abc123def456.apps.googleusercontent.com`

## 2. Paste it into Vigil

1. Open Vigil → **Settings → Sign in with Google**.
2. Paste the client ID → **Save settings**.
3. The login page now shows the Google button.

## 3. Who can sign in?

- **The very first account ever created** (on a fresh install) becomes the
  admin — whether it's made with Google or a password.
- After that, an admin adds people on the **Users** page:
  choose **Google** as the sign-in type and enter their Gmail address.
  Until their email is added, Google sign-in politely refuses them.

## Notes

- Password accounts keep working — Google is an *extra* way in, and the only
  way that works if the venue's internet is down is a password account, so
  keep at least one admin password account.
- Nothing about your cameras or evidence goes to Google. The button only
  verifies **who is signing in**.
- If the button shows an error like `origin not allowed`, the address in your
  browser's URL bar isn't in the **Authorized JavaScript origins** list — add
  it exactly (scheme + host + port) and try again after a minute.
