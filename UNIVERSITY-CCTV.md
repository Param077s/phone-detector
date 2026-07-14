# Connecting university / building CCTV to Vigil

## Where the details go

Dashboard → **+ Add camera** → press **"CCTV / NVR camera? Build the RTSP link"**.
Fill the boxes and Vigil composes the stream link for you, then press **Add camera**.

## What details to ask the CCTV admin for

You need FIVE things (this is the exact list to hand them):

1. **The address (IP) of the camera — or of the NVR/recorder** if cameras run
   through one (most university control rooms do). Example: `10.20.4.15`
2. **The RTSP port** — almost always `554`
3. **A username and password** for viewing streams (a "viewer"/read-only
   account is perfect; you do not need their admin login)
4. **The brand** (Hikvision, Dahua, CP Plus, Uniview, Reolink…) — this decides
   the stream path; Vigil's builder knows the common ones
5. **Which channel number** each camera is on the NVR (camera 1, 2, 3…)

Also ask: *"Is RTSP enabled?"* (it's a checkbox in the camera/NVR settings —
sometimes off by default) and *"Can my laptop reach the camera network?"*
(cameras often live on their own VLAN; if so, ask for a network port or WiFi
that can reach them, or pull streams from the NVR's address instead).

## The two golden rules

- **Always use the substream** (the builder's default). It's the low-resolution
  live view — smooth video, light on the network, and detection accuracy is
  unaffected because the AI resizes frames anyway. The main stream is 4K-heavy
  and will lag.
- **Test one camera before asking for 50.** Add a single camera, confirm live
  video + a detection, then scale.

## Testing a link by hand (optional)

Any `rtsp://…` link that plays in VLC (Media → Open Network Stream) will work
in Vigil. If VLC can't open it, the problem is the link/network, not Vigil:

- Wrong user/pass → auth error
- Wrong path → "not found" (check the brand or use the ONVIF generic option)
- Nothing at all → wrong IP, RTSP disabled, or you're not on the camera VLAN

## NVR quick reference (what the builder generates)

| System | Camera N substream |
|---|---|
| Hikvision NVR | `rtsp://user:pass@NVR-IP:554/Streaming/Channels/N02` (cam 1 → 102, cam 2 → 202…) |
| Dahua / CP Plus | `rtsp://user:pass@NVR-IP:554/cam/realmonitor?channel=N&subtype=1` |
| Reolink | `rtsp://user:pass@IP:554/h264Preview_0N_sub` |
| TP-Link Tapo | `rtsp://user:pass@IP:554/stream2` |
| Unknown brand | try the ONVIF generic option, or ONVIF Device Manager (free tool) shows the exact URL |

## How many cameras can one computer handle?

Rough guide on a modern machine using substreams: **5–15 cameras** with
detection on all of them. For a whole control room (50–100+), you'd run
detection on the cameras that matter (exam halls, entries) or spread across
machines — ask your ML professor about GPU batching for scale.
