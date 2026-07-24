// Instagram publishing via the Meta Graph API.
// Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
//
// Requirements:
//  - The IG account must be a Professional (Business/Creator) account linked
//    to a Facebook Page.
//  - Media must be reachable at a PUBLIC URL (image_url / video_url).
//  - For production posting to accounts you don't own you need App Review for
//    the instagram_content_publish permission + Business Verification.

const { getToken, setToken } = require("./store");
const { redirectUri } = require("./util");

const GRAPH = "https://graph.facebook.com/v21.0";
const SCOPES = [
  "instagram_basic",
  "instagram_content_publish",
  "pages_show_list",
  "business_management",
].join(",");

function authUrl(state) {
  const p = new URLSearchParams({
    client_id: process.env.META_APP_ID || "",
    redirect_uri: redirectUri(),
    scope: SCOPES,
    response_type: "code",
    state,
  });
  return "https://www.facebook.com/v21.0/dialog/oauth?" + p.toString();
}

async function exchangeCode(code) {
  // 1. code -> short-lived user token
  const shortR = await fetch(
    GRAPH + "/oauth/access_token?" +
      new URLSearchParams({
        client_id: process.env.META_APP_ID || "",
        client_secret: process.env.META_APP_SECRET || "",
        redirect_uri: redirectUri(),
        code,
      })
  );
  const short = await shortR.json();
  if (!short.access_token) throw new Error("meta code exchange failed: " + JSON.stringify(short));

  // 2. short-lived -> long-lived (~60 days)
  const longR = await fetch(
    GRAPH + "/oauth/access_token?" +
      new URLSearchParams({
        grant_type: "fb_exchange_token",
        client_id: process.env.META_APP_ID || "",
        client_secret: process.env.META_APP_SECRET || "",
        fb_exchange_token: short.access_token,
      })
  );
  const long = await longR.json();
  const userToken = long.access_token || short.access_token;

  // 3. find the linked IG business account (via the user's Pages)
  const ig = await findIgAccount(userToken);
  if (!ig) throw new Error("No Instagram Professional account found on the connected Facebook Pages");

  await setToken("instagram", {
    access_token: ig.pageToken || userToken,
    ig_user_id: ig.igUserId,
    page_id: ig.pageId,
    expires_at: Date.now() + (long.expires_in || 5184000) * 1000,
  });
  return { ig_user_id: ig.igUserId };
}

async function findIgAccount(userToken) {
  const r = await fetch(
    GRAPH + "/me/accounts?" +
      new URLSearchParams({ fields: "id,name,access_token,instagram_business_account", access_token: userToken })
  );
  const j = await r.json();
  const pages = (j && j.data) || [];
  for (const page of pages) {
    if (page.instagram_business_account && page.instagram_business_account.id) {
      return { igUserId: page.instagram_business_account.id, pageId: page.id, pageToken: page.access_token };
    }
  }
  return null;
}

async function publish({ caption, mediaUrl, mediaType }) {
  const rec = await getToken("instagram");
  if (!rec) throw new Error("Instagram not connected");
  const token = rec.access_token;
  const igId = rec.ig_user_id;
  const isVideo = mediaType && /^video/.test(mediaType);

  // 1. create a media container
  const createParams = { caption: caption || "", access_token: token };
  if (isVideo) {
    createParams.media_type = "REELS";
    createParams.video_url = mediaUrl;
  } else {
    createParams.image_url = mediaUrl;
  }
  const createR = await fetch(GRAPH + "/" + igId + "/media", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(createParams),
  });
  const created = await createR.json();
  if (!created.id) throw new Error("ig container failed: " + JSON.stringify(created));

  // 2. wait for the container to finish processing (video needs a moment)
  if (isVideo) await waitForContainer(created.id, token);

  // 3. publish it
  const pubR = await fetch(GRAPH + "/" + igId + "/media_publish", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ creation_id: created.id, access_token: token }),
  });
  const pub = await pubR.json();
  if (!pub.id) throw new Error("ig publish failed: " + JSON.stringify(pub));
  return { id: pub.id, url: "https://www.instagram.com/p/" + pub.id + "/" };
}

async function waitForContainer(creationId, token, tries) {
  tries = tries || 12; // ~ up to 60s
  for (let i = 0; i < tries; i++) {
    const r = await fetch(GRAPH + "/" + creationId + "?" + new URLSearchParams({ fields: "status_code", access_token: token }));
    const j = await r.json();
    if (j.status_code === "FINISHED") return;
    if (j.status_code === "ERROR") throw new Error("ig media processing error");
    await new Promise((res) => setTimeout(res, 5000));
  }
  throw new Error("ig media still processing after timeout");
}

async function connected() {
  return !!(await getToken("instagram"));
}

module.exports = { authUrl, exchangeCode, publish, connected };
