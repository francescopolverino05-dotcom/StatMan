import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { isLocale, negotiateLocale } from "./content/i18n";

/** Sends addresses without a language prefix to the visitor's language: / becomes /en, /it, ... */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (isLocale(pathname.split("/")[1])) {
    return NextResponse.next();
  }

  // Behind the hosting proxy the public address is in the forwarded headers, not in request.url.
  const forwardedHost = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const host =
    forwardedHost && /^[a-z0-9.-]+(:\d+)?$/i.test(forwardedHost)
      ? forwardedHost
      : request.nextUrl.host;
  const forwardedProto = request.headers.get("x-forwarded-proto");
  const proto =
    forwardedProto === "http" || forwardedProto === "https"
      ? forwardedProto
      : request.nextUrl.protocol.replace(":", "");

  const locale = negotiateLocale(request.headers.get("accept-language"));
  const path = pathname === "/" ? "" : pathname;
  return NextResponse.redirect(`${proto}://${host}/${locale}${path}${search}`);
}

export const config = {
  matcher: ["/((?!_next/|.*\\.[\\w]+$).*)"],
};
