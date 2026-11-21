// Shared R2 responder for the Pages Functions; lives outside functions/ so it is not a route.
export async function serveR2(env, request, key, type, maxAge) {
  const obj = await env.TILES.get(key, { onlyIf: request.headers });
  if (!obj) return new Response("Not found", { status: 404 });
  const headers = new Headers({ "content-type": type, "cache-control": `public, max-age=${maxAge}` });
  headers.set("etag", obj.httpEtag);
  if (!("body" in obj)) return new Response(null, { status: 304, headers });
  return new Response(obj.body, { headers });
}
