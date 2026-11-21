import { serveR2 } from "../../lib/r2.js";

// Shared renders, so contributors can paint without a Google key: /renders/detail/r<row>_c<col>.jpg
export async function onRequestGet({ params, env, request }) {
  const key = "renders/" + params.path.join("/");
  if (!/^renders\/detail\/r-?\d+_c-?\d+\.jpg$/.test(key)) return new Response("Bad path", { status: 400 });
  return serveR2(env, request, key, "image/jpeg", 86400);
}
