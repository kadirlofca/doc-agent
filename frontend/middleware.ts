import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const userId = request.cookies.get("pageindex_user_id")?.value;

  if (userId) {
    return NextResponse.next();
  }

  // First visit: generate user ID and set cookie
  const newUserId = crypto.randomUUID();
  const response = NextResponse.next();
  const isProduction = process.env.NODE_ENV === "production";
  response.cookies.set("pageindex_user_id", newUserId, {
    maxAge: 60 * 60 * 24 * 365,
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: "/",
  });

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
