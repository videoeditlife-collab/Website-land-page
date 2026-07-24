// GET /api/status  -> which platforms are connected + whether media store is set.
// The front end calls this to show "Connect TikTok / Instagram" buttons.

const { json, preflight, requireApiKey } = require("./lib/util");
const tiktok = require("./lib/tiktok");
const instagram = require("./lib/instagram");

exports.handler = async (event) => {
  const pf = preflight(event);
  if (pf) return pf;
  const gate = requireApiKey(event);
  if (gate) return gate;

  const [tk, ig] = await Promise.all([tiktok.connected(), instagram.connected()]);
  return json(200, {
    ok: true,
    connected: { tiktok: tk, instagram: ig },
    mediaConfigured: !!(process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_KEY),
  });
};
