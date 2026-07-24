// GET /api/oauth/start?platform=tiktok|instagram
// Redirects the browser to the platform's consent screen.

const tiktok = require("./lib/tiktok");
const instagram = require("./lib/instagram");
const { cors } = require("./lib/util");

exports.handler = async (event) => {
  const platform = (event.queryStringParameters || {}).platform;
  const state = platform + ":" + Math.random().toString(36).slice(2);

  let url;
  if (platform === "tiktok") url = tiktok.authUrl(state);
  else if (platform === "instagram") url = instagram.authUrl(state);
  else return { statusCode: 400, headers: cors(), body: "unknown platform" };

  return { statusCode: 302, headers: Object.assign({ Location: url }, cors()), body: "" };
};
