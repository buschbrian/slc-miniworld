import { serveR2 } from "../../lib/r2.js";

// The approved style reference every square is painted against: /style/ref.png
export async function onRequestGet({ params, env, request }) {
  if (params.path.join("/") !== "ref.png") return new Response("Not found", { status: 404 });
  return serveR2(env, request, "style/ref.png", "image/png", 86400);
}
