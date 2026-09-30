import { NextRequest, NextResponse } from "next/server";
import { parseAuthEnabled } from "./lib/api";
import { resolveBackendApiBase } from "./lib/backend-runtime-config";
import {
  CODEX_CALLBACK_API_PATH,
  COOKIE_NAME,
  LOGIN_PATH,
  classifyToken,
  isAuthExempt,
  isBackendPath,
  isCodexCallbackPath,
  isRetiredPagePath,
} from "./lib/proxy-policy";

// Backend base URL for `/api/*` and `/ws/*` rewrites. The container entrypoint
// exports `DEEPTUTOR_API_BASE_URL` from `data/user/settings/system.json`
// (preferring `next_public_api_base`, then `next_public_api_base_external`,
// then `http://127.0.0.1:${BACKEND_PORT}`). This last-resort default applies
// only when nothing exported the variable at all.
//
// The loopback is spelled as the IPv4 literal, not `localhost`: on a dual-stack
// host that name resolves to ::1 first, while uvicorn binds 0.0.0.0 (IPv4
// only), so every rewrite would fail to connect.
const API_BASE_URL = resolveBackendApiBase();
const DIGITAL_HUMAN_API_BASE =
  process.env.DIGITAL_HUMAN_API_BASE_URL || "http://127.0.0.1:8010";

const AUTH_ENABLED = parseAuthEnabled(
  process.env.DEEPTUTOR_AUTH_ENABLED ?? process.env.NEXT_PUBLIC_AUTH_ENABLED,
);

// Redirect to the login page, preserving the intended destination in `next`.
// A present-but-invalid cookie is cleared so the browser stops resending it;
// when no cookie was sent there is nothing to clear.
function redirectToLogin(
  req: NextRequest,
  { clearCookie }: { clearCookie: boolean },
): NextResponse {
  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = LOGIN_PATH;
  loginUrl.search = "";
  loginUrl.searchParams.set(
    "next",
    `${req.nextUrl.pathname}${req.nextUrl.search}`,
  );
  const response = NextResponse.redirect(loginUrl);
  if (clearCookie) response.cookies.delete(COOKIE_NAME);
  return response;
}

export async function proxy(req: NextRequest): Promise<NextResponse> {
  const { pathname, search } = req.nextUrl;

  if (isCodexCallbackPath(pathname)) {
    return NextResponse.rewrite(
      new URL(CODEX_CALLBACK_API_PATH + search, API_BASE_URL),
    );
  }

  if (isRetiredPagePath(pathname)) {
    return new NextResponse(null, { status: 404 });
  }

  // 1. Bridge the origin gap: forward backend-relative paths to the API server.
  //    This keeps the URL knowledge in one place (the entrypoint + system.json)
  //    rather than baked into the frontend bundle.
  if (isBackendPath(pathname)) {
    return NextResponse.rewrite(new URL(pathname + search, API_BASE_URL));
  }

  // The digital-human service shares this origin. Apply the UI auth gate
  // before forwarding because LiveTalking does not own DeepTutor sessions.
  if (pathname.startsWith("/digital-api/")) {
    const avatarPath = pathname.slice("/digital-api".length);
    if (
      req.method !== "POST" ||
      !["/offer", "/human", "/interrupt_talk", "/close"].includes(avatarPath)
    ) {
      return new NextResponse(null, { status: 404 });
    }
    // This route uses the browser's auth cookie. Require a same-origin JSON
    // request so a third-party form or no-cors fetch cannot allocate sessions.
    if (req.headers.get("origin") !== req.nextUrl.origin) {
      return NextResponse.json({ code: -1, msg: "请求来源不受信任" }, { status: 403 });
    }
    if (req.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") {
      return NextResponse.json({ code: -1, msg: "只接受 JSON 请求" }, { status: 415 });
    }
    // The backend owns the runtime auth setting. The frontend process can be
    // started separately without DEEPTUTOR_AUTH_ENABLED in its environment.
    try {
      const status = await fetch(new URL("/api/auth/status", API_BASE_URL), {
        headers: { cookie: req.headers.get("cookie") || "" },
        cache: "no-store",
      });
      if (!status.ok) throw new Error("auth status unavailable");
      const auth: unknown = await status.json();
      if (
        !auth ||
        typeof auth !== "object" ||
        typeof (auth as { enabled?: unknown }).enabled !== "boolean" ||
        typeof (auth as { authenticated?: unknown }).authenticated !== "boolean"
      ) {
        throw new Error("invalid auth status");
      }
      const authState = auth as {
        enabled: boolean;
        authenticated: boolean;
        learning_policy?: { allowed_surfaces?: unknown } | null;
      };
      if (authState.enabled && !authState.authenticated) {
        return redirectToLogin(req, {
          clearCookie: Boolean(req.cookies.get(COOKIE_NAME)?.value),
        });
      }
      const surfaces = authState.learning_policy?.allowed_surfaces;
      if (Array.isArray(surfaces) && !surfaces.includes("chat")) {
        return NextResponse.json({ code: -1, msg: "当前账号不能使用互动答疑" }, { status: 403 });
      }
    } catch {
      return NextResponse.json({ code: -1, msg: "教学服务暂时不可用" }, { status: 503 });
    }
    return NextResponse.rewrite(
      new URL(avatarPath + search, DIGITAL_HUMAN_API_BASE),
    );
  }

  // 2. Auth gate — multi-user mode only. Disabled by default, and never blocks
  //    auth pages, Next.js internals, or public static assets (see
  //    isAuthExempt: that exemption is what keeps the logo/banner images
  //    loading once login is enabled — issue #599).
  if (!AUTH_ENABLED || isAuthExempt(pathname)) {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;
  if (classifyToken(token, Date.now()) !== "valid") {
    return redirectToLogin(req, { clearCookie: Boolean(token) });
  }

  return NextResponse.next();
}

export const config = {
  // Run on every request except Next.js internals and the favicon. The /api/*
  // and /ws/* paths are explicitly handled above (rewritten to the backend);
  // large knowledge create/upload requests are handled by dedicated App Router
  // endpoints that stream directly to FastAPI. The collection handler also
  // forwards GET because a route module owns every method at that pathname.
  // Excluding these endpoints here is crucial:
  // merely entering Proxy makes Next clone and cap the multipart body.
  // the browser's /_next/image optimizer requests are excluded here, while the
  // optimizer's loopback fetch for the source image (e.g. /logo.png) is let
  // through the auth gate by isAuthExempt.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/knowledge-bases(?:$|/[^/]+/upload(?:/|$))).*)",
  ],
};
