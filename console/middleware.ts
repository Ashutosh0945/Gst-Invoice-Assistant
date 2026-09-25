import { NextResponse, type NextRequest } from "next/server";

// Every console page requires a signed-in *staff* account. The check runs on the
// server before any page renders, by asking the API who the visitor's session belongs to.
export async function middleware(req: NextRequest) {
  const backend = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
  const cookie = req.cookies.get("session")?.value;
  if (cookie) {
    try {
      const r = await fetch(`${backend}/api/v1/console/me`, { headers: { cookie: `session=${cookie}` }, cache: "no-store" });
      if (r.ok) return NextResponse.next();
    } catch {
      /* API unreachable: fall through to the login page */
    }
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except the login page, the API proxy and static files.
  matcher: ["/((?!login|api/|_next/|favicon.ico|robots.txt).*)"],
};
