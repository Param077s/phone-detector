# Signing in to Vigil

Vigil has **two ways to sign in** — you don't set up anything, both just work:

## 1. Sign in with Google (on the Vigil computer)

When you open Vigil on the computer it's running on (`http://localhost:8000`),
the login page shows a **"Sign in with Google"** button. Click it, pick your
Google account, and you're in. Nothing to configure.

- The **first person** to sign in (Google or password) becomes the **admin**.
- After that, the admin adds each teammate on the **Users** page — for Google
  users, just enter their Gmail address. Until an email is added, Google
  politely refuses that person (so randoms can't get in).

## 2. Username + password (anywhere)

Every account can also have a username + password. Use this:

- **On a phone or another device** (opening Vigil over WiFi at
  `http://<computer-ip>:8000`). Google's button only works on the Vigil
  computer itself — a Google rule we can't change — so phones use the
  password you were given.
- **When the internet is down.** Password sign-in needs no internet; Google
  sign-in does. Always keep at least one admin **password** account as a
  backup.

## Why is there a login at all? (it's local!)

Because the **evidence log holds photos of people**. The login keeps that
private — especially the moment you view Vigil from a phone or share a link,
which puts it on the network. Vigil records **nothing about you**: accounts
live in a local file on that computer, passwords are stored only as a one-way
hash, and nothing is ever sent anywhere.

---

### For developers / self-hosting on your own domain

Google Sign-In is pre-configured with a built-in client ID that authorizes
`localhost`. If you host Vigil on a public domain and want the Google button
to work there too, set your own OAuth **Web application** client ID via the
`GOOGLE_CLIENT_ID` environment variable (authorize your domain as a JavaScript
origin in the Google Cloud console). Everyone else can ignore this.
