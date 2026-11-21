// Serves map tiles from the private R2 bucket: /tiles/<layer>/<z>/<x>/<y>.jpg -> key <layer>/<z>/<x>/<y>.jpg
export async function onRequestGet({ params, env, request }) {
  const key = params.path.join("/");
  if (!/^[\w-]+\/\d+\/-?\d+\/-?\d+\.jpg$/.test(key)) return new Response("Bad tile path", { status: 400 });
  const obj = await env.TILES.get(key, { onlyIf: request.headers });
  if (!obj) return new Response("Not found", { status: 404 });
  const headers = new Headers({ "content-type": "image/jpeg", "cache-control": "public, max-age=86400" });
  headers.set("etag", obj.httpEtag);
  if (!("body" in obj)) return new Response(null, { status: 304, headers });
  return new Response(obj.body, { headers });
}
