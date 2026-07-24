// POST /api/publish
//   { id, platform, caption, scheduledAt, mediaUrl, mediaType }
//
//   scheduledAt in the future -> stored in the queue; the cron scheduler
//                                 (scheduler.js) publishes it when due.
//   scheduledAt null / past   -> published immediately.

const { json, preflight, requireApiKey } = require("./lib/util");
const { putQueueItem } = require("./lib/store");
const tiktok = require("./lib/tiktok");
const instagram = require("./lib/instagram");

const PLATFORMS = { tiktok, instagram };

async function publishNow(item) {
  const mod = PLATFORMS[item.platform];
  if (!mod) throw new Error("unknown platform: " + item.platform);
  return mod.publish({ caption: item.caption, mediaUrl: item.mediaUrl, mediaType: item.mediaType });
}

exports.handler = async (event) => {
  const pf = preflight(event);
  if (pf) return pf;
  if (event.httpMethod !== "POST") return json(405, { ok: false, error: "POST only" });
  const gate = requireApiKey(event);
  if (gate) return gate;

  let b = {};
  try { b = JSON.parse(event.body || "{}"); } catch (e) { return json(400, { ok: false, error: "bad json" }); }

  const item = {
    id: b.id || Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
    platform: b.platform,
    caption: b.caption || "",
    mediaUrl: b.mediaUrl || (b.media && b.media.url) || null,
    mediaType: b.mediaType || (b.media && b.media.type) || null,
    scheduledAt: b.scheduledAt || null,
    status: "scheduled",
    attempts: 0,
    createdAt: new Date().toISOString(),
  };

  if (!PLATFORMS[item.platform]) return json(400, { ok: false, error: "unknown platform" });

  const due = !item.scheduledAt || new Date(item.scheduledAt).getTime() <= Date.now();

  if (!due) {
    // schedule for later — the cron function will fire it
    await putQueueItem(item);
    return json(200, { ok: true, queued: true, id: item.id, scheduledAt: item.scheduledAt });
  }

  // publish right now
  try {
    const res = await publishNow(item);
    item.status = "posted";
    item.postedAt = new Date().toISOString();
    item.result = res;
    await putQueueItem(item);
    return json(200, { ok: true, url: res.url || null, id: item.id });
  } catch (e) {
    item.status = "failed";
    item.error = e.message;
    item.attempts = 1;
    await putQueueItem(item);
    return json(502, { ok: false, error: e.message, id: item.id });
  }
};
