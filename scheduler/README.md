# Cross-Post Scheduler

Compose a post once, then publish or schedule it to **TikTok and Instagram at
the same time** — one click, one queue.

- **Front end:** `scheduler/index.html` (open at `/scheduler/` on the site)
- **Backend:** Netlify Functions + a cron scheduler in `netlify/functions/`
- **Cost:** runs on free tiers (Netlify + Supabase Storage). The platform APIs are free.

---

## Two modes

**Simulation (default, no setup).** The whole workflow runs in your browser and
is saved in `localStorage`. Publishing is faked so you can try everything.
Scheduling only fires while the tab is open.

**Connected (real posting).** Point the app at the deployed backend. It uploads
media to storage, posts through the official APIs, and a cron function fires
scheduled posts even with no browser open.

---

## Deploy the backend (one-time)

### 1. TikTok app — free
1. developers.tiktok.com → **Manage apps** → create an app.
2. Add the **Content Posting API** product. Request scopes `video.publish` and `video.upload`.
3. Redirect URI: `https://YOURSITE.netlify.app/api/oauth/callback`
4. For **PULL_FROM_URL** posting, verify your media domain under **URL properties**
   (use your Supabase project domain).
5. Copy the **Client key / Client secret**.

> Until TikTok **audits** your app, posts must be `SELF_ONLY` (visible to you).
> After audit, flip `TIKTOK_PRIVACY_LEVEL` to `PUBLIC_TO_EVERYONE`.

### 2. Meta / Instagram app — free
1. The IG account must be **Professional (Business/Creator)** and linked to a Facebook Page.
2. developers.facebook.com → create an app → add **Instagram Graph API** + **Facebook Login**.
3. Request the `instagram_content_publish`, `instagram_basic`, `pages_show_list`,
   `business_management` permissions (App Review + Business Verification for production).
4. Redirect URI: `https://YOURSITE.netlify.app/api/oauth/callback`
5. Copy the **App ID / App secret**.

### 3. Media storage — Supabase, free
Netlify functions can't accept large video uploads (6 MB body limit), so media
is uploaded straight from the browser to storage via a signed URL.
1. supabase.com → new project → **Storage** → create a **public** bucket named `media`.
2. Project settings → API → copy the **Project URL** and **service_role key**.

### 4. Set environment variables on Netlify
Site settings → **Environment variables** — fill in the values from `.env.example`:
`TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_PRIVACY_LEVEL`,
`META_APP_ID`, `META_APP_SECRET`,
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET`,
and optionally `API_KEY` (a shared secret the app sends as `x-api-key`).

Deploy. Netlify installs the functions and enables the every-minute scheduler
automatically (`netlify.toml`).

### 5. Connect the app
Open `/scheduler/` → click **Simulation mode** (top-right) → set the backend URL
to `https://YOURSITE.netlify.app/api` (and the API key if you set one). A green
panel appears — click **Connect TikTok** and **Connect Instagram** once each.
Done: post-now fans out for real, and scheduled posts fire from the cron.

---

## How it fits together

```
Browser (scheduler/index.html)
  │  1. POST /api/upload-url      -> signed URL + public URL
  │  2. PUT  <signed URL>         -> media lands in Supabase (public)
  │  3. POST /api/publish         -> post now, or enqueue if scheduled
  ▼
Netlify Functions
  publish.js     now  -> tiktok/instagram publish();  later -> queue (Netlify Blobs)
  scheduler.js   cron every minute -> publishes due queue items
  oauth-*.js     link accounts, tokens stored in Netlify Blobs (auto-refresh)
  status.js      which accounts are linked
  queue.js       queue statuses (the app syncs these back)
```

### The `/publish` contract

```
POST {BACKEND}/publish        (x-api-key if API_KEY is set)
{
  "id": "abc-tiktok",
  "platform": "tiktok" | "instagram",
  "caption": "text incl. hashtags",
  "scheduledAt": "2026-07-24T15:00:00.000Z" | null,   // null/past = now
  "mediaUrl": "https://.../media/x.mp4" | null,
  "mediaType": "video/mp4" | "image/jpeg" | null
}
-> { "ok": true, "url": "..." }        // posted now
-> { "ok": true, "queued": true }      // scheduled for later
-> { "ok": false, "error": "reason" }  // or non-200
```

---

## Files

```
scheduler/index.html          the app (no build step)
scheduler/README.md           this file
netlify.toml                  functions dir, /api/* redirects, cron schedule
.env.example                  the env vars to set on Netlify
netlify/functions/
  status.js  oauth-start.js  oauth-callback.js
  upload-url.js  publish.js  queue.js  scheduler.js (cron)
  lib/  util.js  store.js  tiktok.js  instagram.js
```

## Good to know

- **TikTok audit**: direct public posting needs TikTok to approve the app; before
  that it's `SELF_ONLY`. This is a platform rule, not a code limit.
- **Instagram limits**: ~50 API posts / 24h; video must finish processing (the
  backend polls) before it publishes.
- **Tokens**: TikTok access tokens auto-refresh; the Instagram long-lived token
  lasts ~60 days — re-click **Connect Instagram** when it expires.
