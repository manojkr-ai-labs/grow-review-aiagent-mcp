import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Public console: do not ask for a username or password.
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
