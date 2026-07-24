// Shared helpers: CORS, JSON responses, API-key gate, site URL.

function cors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, x-api-key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };
}

function json(statusCode, body, extra) {
  return {
    statusCode,
    headers: Object.assign({ "Content-Type": "application/json" }, cors(), extra || {}),
    body: JSON.stringify(body),
  };
}

function preflight(event) {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: cors(), body: "" };
  return null;
}

// If API_KEY is set in the environment, require the caller to send it.
// Returns an error response to short-circuit, or null when the call may proceed.
function requireApiKey(event) {
  const need = process.env.API_KEY;
  if (!need) return null;
  const h = event.headers || {};
  const got = h["x-api-key"] || h["X-Api-Key"] || h["x-Api-Key"];
  if (got !== need) return json(401, { ok: false, error: "invalid api key" });
  return null;
}

// The site's public base URL (Netlify sets URL automatically on deploy).
function siteUrl() {
  return (process.env.PUBLIC_URL || process.env.URL || "").replace(/\/$/, "");
}

function redirectUri() {
  return siteUrl() + "/api/oauth/callback";
}

module.exports = { cors, json, preflight, requireApiKey, siteUrl, redirectUri };
