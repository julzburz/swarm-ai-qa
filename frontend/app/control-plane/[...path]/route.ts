import type { NextRequest } from "next/server";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

const controlPlane = (
  process.env.SWARM_CONTROL_PLANE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const upstream = new URL(
    `/${path.map((segment) => encodeURIComponent(segment)).join("/")}`,
    controlPlane,
  );
  upstream.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("authorization");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("expect");
  headers.delete("host");
  headers.delete("keep-alive");
  headers.delete("proxy-authenticate");
  headers.delete("proxy-authorization");
  headers.delete("te");
  headers.delete("trailer");
  headers.delete("transfer-encoding");
  headers.delete("upgrade");

  const apiKey = process.env.SWARM_CONTROL_PLANE_API_KEY?.trim();
  if (apiKey) {
    headers.set("authorization", `Bearer ${apiKey}`);
  }

  const response = await fetch(upstream, {
    method: request.method,
    headers,
    body:
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer(),
    cache: "no-store",
    redirect: "manual",
  });

  const responseHeaders = new Headers(response.headers);
  responseHeaders.delete("connection");
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");

  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export const dynamic = "force-dynamic";

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
