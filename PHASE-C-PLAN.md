# Phase C — Cloud / Hosted Vigil (PLAN, not built yet)

Turns Vigil from "download & self-host" into "sign up on a website." This is a
real re-architecture and needs decisions + a cloud account, so this doc is the
plan we lock before building. Self-hosted stays available — cloud is an addition.

---

## The core split

Because cameras live on private networks (a webcam or CCTV behind a router can't be
reached from the internet), the cloud version splits Vigil into two pieces:

```
   ┌─────────────────────────────────────────────┐
   │  CLOUD DASHBOARD  (we host it)               │
   │  accounts · alerts · evidence log · billing  │
   │  signalling + relay for shared cameras       │
   └─────────────────────────────────────────────┘
        ▲ only small alerts (+ shared-cam streams)
        │  internet
        ▼
   ┌─────────────────────────────────────────────┐
   │  ON-SITE CONNECTOR  (slimmed installer)      │
   │  reaches LOCAL cameras · runs YOLO on-site   │
   │  sends only alerts up  ·  video stays local  │
   └─────────────────────────────────────────────┘
        │
   local cameras (webcam / RTSP CCTV)
```

- **Local cameras** → handled by the on-site connector. Private (video never
  leaves the building); only alerts go to the cloud. This is the main product.
- **Remote / ad-hoc cameras** → handled by *share-a-camera-by-link* (below).

---

## ⭐ Feature: Share a camera by link (no install for the sharer)

Goal: an admin sends a link; the other person (e.g. a brother in another country)
opens it in a browser, clicks **Allow camera**, and their camera appears in the
admin's dashboard — **with nothing to install.**

**How it works**
1. Admin clicks **"Share a camera"** → cloud generates a **one-time, revocable link**
   (a scoped token tied to the admin's account, with a label/location).
2. The person opens the link in any modern browser. The page asks for camera
   permission (`getUserMedia`) — no app, just click **Allow**.
3. The browser streams video via **WebRTC**. Because the two sides are on different
   networks, the cloud provides:
   - **signalling** (the two browsers/servers exchange connection info), and
   - **STUN/TURN** servers to punch through NAT (**TURN = a relay** for when a direct
     peer-to-peer link isn't possible — most cross-network cases).
4. The stream lands at the cloud, where **detection runs in the cloud** for shared
   cameras (there's no on-site connector for a random browser camera). Alerts flow
   into the same dashboard as everything else.
5. Admin can **revoke** the link/camera anytime; it can be one-session or persistent.

**Honest trade-offs of shared cameras**
- The sharer's **video leaves their device** and crosses the internet (privacy note).
- **We pay** for TURN relay bandwidth + cloud detection (GPU). Fine for a few ad-hoc
  cameras; expensive at scale — so this is best as a *convenience/demo* feature, not
  the way you'd wire 100 exam-hall cameras (those use the on-site connector).
- Continuous long-distance streaming has **latency + bandwidth** costs.

**Where it shines:** quick "show me your camera" setups, remote helpers, demos, and
small deployments where installing a connector isn't worth it.

---

## Components to build

1. **Cloud dashboard** — the current web UI (accounts, live view, alerts, evidence,
   users) hosted online, multi-tenant (each org's data separated).
2. **On-site connector** — the installer we built, slimmed to: reach local cameras,
   run YOLO, push alerts to the cloud (no local web UI needed).
3. **Realtime layer** — WebRTC signalling + STUN/TURN for share-a-camera-by-link.
4. **Cloud detection worker** — runs YOLO on shared-camera streams (GPU or sampled
   frames to control cost).
5. **Accounts/billing** — orgs sign up; free pilot tier vs paid.

---

## Open decisions (need you)

- **Hosting:** which platform (and you'll need an account + card there).
- **Where detection runs for shared cameras:** cloud GPU (fast, costs more) vs
  sampled CPU frames (cheaper, slower). Start cheap.
- **Data policy:** do alert **photos** get stored in the cloud, or only metadata +
  kept on-site? (Big privacy/marketing call.)
- **Billing:** free pilot vs paid tiers; per-camera or per-org.
- **TURN provider:** run our own or use a managed TURN service (relay bandwidth = a
  real cost driver).

---

## Suggested build order (within Phase C)

1. Host the existing dashboard in the cloud with accounts (multi-tenant).
2. Slim the installer into the on-site connector (local detection → push alerts).
3. Add **share-a-camera-by-link** (WebRTC + TURN + cloud detection) — the
   no-install remote-camera flow.
4. Billing + polish.

Do 1–2 first (that's the real product); 3 (share-by-link) is the delightful extra
that makes onboarding and demos effortless.

---

*Status: planning only. Current focus is piloting the self-hosted version first
(see PILOT.md). Build Phase C after the pilot proves the concept.*
