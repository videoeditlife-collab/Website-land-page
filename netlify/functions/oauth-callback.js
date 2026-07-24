// GET /api/oauth/callback?code=...&state=<platform>:<nonce>
// Exchanges the code for tokens, stores them, and bounces back to the app.

const tiktok = require("./lib/tiktok");
const instagram = require("./lib/instagram");
const { siteUrl } = require("./lib/util");

exports.handler = async (event) => {
  const q = event.queryStringParameters || {};
  const platform = (q.state || "").split(":")[0];
  const back = (ok, msg) =>
    ({ statusCode: 302, headers: { Location: siteUrl() + "/scheduler/?connected=" + platform + (ok ? "" : "&error=" + encodeURIComponent(msg || "failed")) }, body: "" });

  if (q.error) return back(false, q.error_description || q.error);
  if (!q.code) return back(false, "missing code");

  try {
    if (platform === "tiktok") await tiktok.exchangeCode(q.code);
    else if (platform === "instagram") await instagram.exchangeCode(q.code);
    else return back(false, "unknown platform");
    return back(true);
  } catch (e) {
    return back(false, e.message);
  }
};
