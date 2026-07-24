# Cross-Post Scheduler

Compose a post once, then publish or schedule it to **TikTok and Instagram at
the same time** — one click, one queue.

Open it at **`/scheduler/`** on the site (e.g. `https://yoursite.netlify.app/scheduler/`).

---

## What works today (simulation mode)

The whole workflow is live and runs entirely in your browser:

- One composer → pick TikTok, Instagram, or both.
- **Post now** fans out to every selected platform at once.
- **Schedule** for a date/time; the queue fires it when it's due.
- Per-platform caption overrides, hashtags, media preview.
- A queue with per-platform status (queued → publishing → posted / failed),
  retry, delete, details, and export.

In simulation mode the publishing step is **faked** — nothing is sent to TikTok
or Instagram. Everything is saved in `localStorage` on this browser only.

> Scheduling in simulation mode only fires while the tab is open. Real,
> tab-closed scheduling needs the backend below (a server that's always on).

---

## Making it post for real

Neither platform lets a web page post directly — a small backend has to hold
your OAuth tokens and call the official APIs. This front end is already built to
talk to one.

### 1. Developer apps (free, one-time)

| Platform | What to set up | Catch |
|---|---|---|
| **TikTok** | Developer app with the **Content Posting API** | Until TikTok audits the app it can only push to your **drafts** (you tap "Post" in the app). After audit it posts directly. |
| **Instagram** | Account must be **Professional** (Business/Creator) linked to a Facebook Page. Meta app with **Instagram Graph API** + `instagram_content_publish` permission (App Review for production). | Video/Reels must be uploaded to a **public URL** first, then published. Rate limited (~50 posts / 24h). |

### 2. The backend contract

The front end calls **one endpoint**. Set its base URL via the "Simulation
mode" button in the app (top-right) — that flips it to real posting.

```
POST  {BACKEND_URL}/publish
Headers: Content-Type: application/json
         x-api-key: <optional, if you set one in the app>

Body:
{
  "platform":   "tiktok" | "instagram",
  "caption":    "final caption text incl. hashtags",
  "scheduledAt": "2026-07-24T15:00:00.000Z" | null,   // null = now
  "media":      { "name": "reel.mp4", "type": "video/mp4" } | null
}

200 OK:
{ "ok": true, "url": "https://www.tiktok.com/@you/video/123" }   // url optional

Error:
{ "ok": false, "error": "human-readable reason" }                // or any non-200
```

The backend is responsible for: holding the OAuth tokens, uploading the media
to each platform, and (if `scheduledAt` is set) running the timer so posts fire
even when no browser is open. A ~150-line Netlify Function + scheduled function,
or a small Express app, covers it.

### 3. Media upload note

This front end sends caption + media **metadata**, not the raw file bytes (a
browser can't safely stream large videos straight to the platform APIs). For a
production setup the backend should accept the actual upload — the simplest
version has the SMM upload media to the backend / a storage bucket, and the
backend hands the public URL to Instagram and the file to TikTok.

---

## Want the backend built?

Ask Claude: **"build the scheduler backend"** — it'll generate the `/publish`
endpoint, the OAuth flows for both platforms, and the scheduler, wired to this
front end's contract above.

## Files

- `scheduler/index.html` — the whole app (no dependencies, no build step).
- `scheduler/README.md` — this file.
