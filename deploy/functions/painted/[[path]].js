import { serveR2 } from "../../lib/r2.js";

// Painted squares for contributors' seam context: /painted/detail/r<row>_c<col>.png
export async function onRequestGet({ params, env, request }) {
  const key = "painted/" + params.path.join("/");
  if (!/^painted\/detail\/r-?\d+_c-?\d+\.png$/.test(key)) return new Response("Bad path", { status: 400 });
  return serveR2(env, request, key, "image/png", 3600);
}
