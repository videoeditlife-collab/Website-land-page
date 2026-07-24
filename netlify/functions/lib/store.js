// Persistence on Netlify Blobs (free, no setup — enabled automatically).
//   tokens store:  key = "tiktok" | "instagram"  -> OAuth token record
//   queue  store:  key = "<postId>:<platform>"    -> scheduled/posted item

const { getStore } = require("@netlify/blobs");

const tokensStore = () => getStore("tokens");
const queueStore = () => getStore("queue");

async function getToken(platform) {
  try {
    return await tokensStore().get(platform, { type: "json" });
  } catch (e) {
    return null;
  }
}

async function setToken(platform, record) {
  await tokensStore().setJSON(platform, record);
}

async function deleteToken(platform) {
  try { await tokensStore().delete(platform); } catch (e) {}
}

function queueKey(item) {
  return item.id + ":" + item.platform;
}

async function putQueueItem(item) {
  await queueStore().setJSON(queueKey(item), item);
}

async function getQueueItem(key) {
  try { return await queueStore().get(key, { type: "json" }); } catch (e) { return null; }
}

async function listQueue() {
  const out = [];
  const { blobs } = await queueStore().list();
  for (const b of blobs) {
    const item = await getQueueItem(b.key);
    if (item) out.push(item);
  }
  // newest first
  out.sort((a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""));
  return out;
}

module.exports = {
  getToken, setToken, deleteToken,
  putQueueItem, getQueueItem, listQueue, queueKey,
};
