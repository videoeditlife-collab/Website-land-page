// TikTok Content Posting API.
// Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
//
// Notes that matter in practice:
//  - Direct posting (video shows up published) requires your app to pass
//    TikTok's audit. Until then, unaudited apps can only post as SELF_ONLY
//    and/or push to the creator's inbox as a draft.
//  - PULL_FROM_URL requires the media domain to be verified under
//    "URL properties" in the TikTok developer portal.

const { getToken, setToken } = require("./store");
const { redirectUri } = require("./util");

const AUTH = "https://www.tiktok.com/v2/auth/authorize/";
const TOKEN = "https://open.tiktokapis.com/v2/oauth/token/";
const SCOPES = "user.info.basic,video.publish,video.upload";

function authUrl(state) {
  const p = new URLSearchParams({
    client_key: process.env.TIKTOK_CLIENT_KEY || "",
    scope: SCOPES,
    response_type: "code",
    redirect_uri: redirectUri(),
    state,
  });
  return AUTH + "?" + p.toString();
}

async function exchangeCode(code) {
  const body = new URLSearchParams({
    client_key: process.env.TIKTOK_CLIENT_KEY || "",
    client_secret: process.env.TIKTOK_CLIENT_SECRET || "",
    code,
    grant_type: "authorization_code",
    redirect_uri: redirectUri(),
  });
  const r = await fetch(TOKEN, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const j = await r.json();
  if (!j.access_token) throw new Error("tiktok token exchange failed: " + JSON.stringify(j));
  await saveToken(j);
  return j;
}

async function refresh(record) {
  const body = new URLSearchParams({
    client_key: process.env.TIKTOK_CLIENT_KEY || "",
    client_secret: process.env.TIKTOK_CLIENT_SECRET || "",
    grant_type: "refresh_token",
    refresh_token: record.refresh_token,
  });
  const r = await fetch(TOKEN, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const j = await r.json();
  if (!j.access_token) throw new Error("tiktok refresh failed: " + JSON.stringify(j));
  await saveToken(j);
  return j;
}

async function saveToken(j) {
  await setToken("tiktok", {
    access_token: j.access_token,
    refresh_token: j.refresh_token,
    open_id: j.open_id,
    scope: j.scope,
    expires_at: Date.now() + (j.expires_in || 86400) * 1000,
  });
}

// Return a valid access token, refreshing if it is expired/near expiry.
async function validToken() {
  let rec = await getToken("tiktok");
  if (!rec) throw new Error("TikTok not connected");
  if (Date.now() > (rec.expires_at || 0) - 60000) rec = await refresh(rec);
  return rec.access_token;
}

// Publish a video (or photo) that is already hosted at a public URL.
async function publish({ caption, mediaUrl, mediaType }) {
  const token = await validToken();
  const privacy = process.env.TIKTOK_PRIVACY_LEVEL || "SELF_ONLY";
  const isVideo = !mediaType || /^video/.test(mediaType);

  const endpoint = isVideo
    ? "https://open.tiktokapis.com/v2/post/publish/video/init/"
    : "https://open.tiktokapis.com/v2/post/publish/content/init/";

  const post_info = {
    title: (caption || "").slice(0, 2200),
    privacy_level: privacy,
    disable_comment: false,
    disable_duet: false,
    disable_stitch: false,
  };

  const body = isVideo
    ? { post_info, source_info: { source: "PULL_FROM_URL", video_url: mediaUrl } }
    : {
        post_info,
        source_info: { source: "PULL_FROM_URL", photo_images: [mediaUrl], photo_cover_index: 0 },
        media_type: "PHOTO",
        post_mode: "DIRECT_POST",
      };

  const r = await fetch(endpoint, {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json; charset=UTF-8" },
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!j.data || (j.error && j.error.code && j.error.code !== "ok")) {
    throw new Error("tiktok publish failed: " + JSON.stringify(j.error || j));
  }
  return { id: j.data.publish_id, url: null };
}

async function connected() {
  return !!(await getToken("tiktok"));
}

module.exports = { authUrl, exchangeCode, publish, connected };
