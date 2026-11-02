/**
 * Same-origin proxy to the FastAPI backend.
 *
 * The browser only ever talks to this origin, so the session cookie stays first-party
 * (SameSite=Lax works on mobile/PWA) and the backend URL is never exposed to the client.
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "host", "content-length",
]);

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const { path } = await ctx.params;
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, backend);
  target.search = req.nextUrl.search;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set("x-forwarded-host", req.headers.get("host") ?? "");

  const hasBody = !["GET", "HEAD"].includes(req.method);
  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  });

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "set-cookie") out.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
