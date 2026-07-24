// GET /api/queue  -> the server-side queue (scheduled + posted history).
// The front end calls this to sync the statuses of posts it handed to the
// server for scheduling.

const { json, preflight, requireApiKey } = require("./lib/util");
const { listQueue } = require("./lib/store");

exports.handler = async (event) => {
  const pf = preflight(event);
  if (pf) return pf;
  const gate = requireApiKey(event);
  if (gate) return gate;

  const items = await listQueue();
  // trim payload to what the UI needs
  const slim = items.map((i) => ({
    id: i.id, platform: i.platform, status: i.status,
    scheduledAt: i.scheduledAt, postedAt: i.postedAt || null,
    url: (i.result && i.result.url) || null, error: i.error || null,
  }));
  return json(200, { ok: true, items: slim });
};
