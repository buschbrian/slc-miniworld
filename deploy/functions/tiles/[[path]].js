import { serveR2 } from "../../lib/r2.js";

// Map tiles: /tiles/<layer>/<z>/<x>/<y>.jpg -> key <layer>/<z>/<x>/<y>.jpg
export async function onRequestGet({ params, env, request }) {
  const key = params.path.join("/");
  if (!/^[\w-]+\/\d+\/-?\d+\/-?\d+\.jpg$/.test(key)) return new Response("Bad tile path", { status: 400 });
  return serveR2(env, request, key, "image/jpeg", 86400);
}
