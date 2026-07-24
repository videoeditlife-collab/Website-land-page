// Scheduled function — runs every minute (see netlify.toml).
// Publishes any queued post whose time has come.

const { listQueue, putQueueItem } = require("./lib/store");
const tiktok = require("./lib/tiktok");
const instagram = require("./lib/instagram");

const PLATFORMS = { tiktok, instagram };
const MAX_ATTEMPTS = 3;

exports.handler = async () => {
  const now = Date.now();
  const items = await listQueue();
  let fired = 0;

  for (const item of items) {
    if (item.status !== "scheduled") continue;
    if (!item.scheduledAt || new Date(item.scheduledAt).getTime() > now) continue;

    const mod = PLATFORMS[item.platform];
    if (!mod) { item.status = "failed"; item.error = "unknown platform"; await putQueueItem(item); continue; }

    item.status = "publishing";
    item.attempts = (item.attempts || 0) + 1;
    await putQueueItem(item);

    try {
      const res = await mod.publish({ caption: item.caption, mediaUrl: item.mediaUrl, mediaType: item.mediaType });
      item.status = "posted";
      item.postedAt = new Date().toISOString();
      item.result = res;
      fired++;
    } catch (e) {
      item.error = e.message;
      // retry on the next run, up to MAX_ATTEMPTS, otherwise give up
      item.status = item.attempts >= MAX_ATTEMPTS ? "failed" : "scheduled";
    }
    await putQueueItem(item);
  }

  return { statusCode: 200, body: "fired " + fired };
};
