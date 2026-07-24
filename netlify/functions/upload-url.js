// POST /api/upload-url   { name, type }
// Returns a one-time signed URL so the browser can upload the media file
// DIRECTLY to storage (bypassing Netlify's 6 MB function-body limit — videos
// are big), plus the public URL the platforms will pull from.
//
// Uses Supabase Storage (free tier). Create a PUBLIC bucket and set:
//   SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_BUCKET (default "media")

const { createClient } = require("@supabase/supabase-js");
const { json, preflight, requireApiKey } = require("./lib/util");

exports.handler = async (event) => {
  const pf = preflight(event);
  if (pf) return pf;
  if (event.httpMethod !== "POST") return json(405, { ok: false, error: "POST only" });
  const gate = requireApiKey(event);
  if (gate) return gate;

  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  const bucket = process.env.SUPABASE_BUCKET || "media";
  if (!url || !key) return json(500, { ok: false, error: "media storage not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY)" });

  let body = {};
  try { body = JSON.parse(event.body || "{}"); } catch (e) {}
  const safe = (body.name || "upload").replace(/[^a-zA-Z0-9._-]/g, "_");
  const path = Date.now() + "-" + Math.random().toString(36).slice(2, 8) + "-" + safe;

  const supabase = createClient(url, key);
  const { data, error } = await supabase.storage.from(bucket).createSignedUploadUrl(path);
  if (error) return json(500, { ok: false, error: error.message });

  const publicUrl = url.replace(/\/$/, "") + "/storage/v1/object/public/" + bucket + "/" + path;
  return json(200, { ok: true, signedUrl: data.signedUrl, token: data.token, path, publicUrl });
};
