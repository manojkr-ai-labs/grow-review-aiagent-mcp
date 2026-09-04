import { NextRequest, NextResponse } from "next/server";

const OPEN_PATHS = new Set(["/health"]);

function unauthorized(): NextResponse {
  return new NextResponse("Authentication required.\n", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="ReviewPulse", charset="UTF-8"',
    },
  });
}

function safeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let i = 0; i < left.length; i += 1) {
    mismatch |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return mismatch === 0;
}

function basicUserPass(): { user: string; password: string } | null {
  const user = process.env.CONSOLE_BASIC_USER?.trim() ?? "";
  const password = process.env.CONSOLE_BASIC_PASSWORD ?? "";
  if (!user || !password) return null;
  return { user, password };
}

function authorized(request: NextRequest): boolean {
  const creds = basicUserPass();
  if (!creds) return true;
  const header = request.headers.get("authorization");
  if (!header || !header.toLowerCase().startsWith("basic ")) return false;
  let decoded: string;
  try {
    decoded = atob(header.slice(6).trim());
  } catch {
    return false;
  }
  return safeEqual(decoded, `${creds.user}:${creds.password}`);
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (OPEN_PATHS.has(pathname) || pathname.startsWith("/_next/")) {
    return NextResponse.next();
  }
  if (!authorized(request)) {
    return unauthorized();
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
