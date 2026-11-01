"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { footerGroups, mobileExtraNav, pageNav } from "@/lib/site-nav";

// Static export serves one 404.html for every missing path, so the requested
// URL is only known after mount. The first render shows nothing extra to keep
// hydration clean.

function useMissingPath(): string | null {
  const [path, setPath] = useState<string | null>(null);
  useEffect(() => {
    const { pathname } = window.location;
    if (pathname && pathname !== "/404/" && pathname !== "/404.html") {
      setPath(decodeURIComponent(pathname).slice(0, 80));
    }
  }, []);
  return path;
}

// Every internal page the site links from its header and footer.
const knownPages = Array.from(
  new Set(
    [...pageNav, ...mobileExtraNav, ...footerGroups.flatMap((g) => g.links)]
      .map((link) => link.href)
      .filter((href) => href.startsWith("/") && !href.startsWith("/#") && href !== "/"),
  ),
);

function editDistance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const current = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = current;
    }
  }
  return row[b.length];
}

const normalize = (path: string) => `/${path.toLowerCase().replace(/^\/+|\/+$/g, "")}/`;

export function suggestPage(path: string, pages: string[] = knownPages): string | null {
  const target = normalize(path);
  let best: { href: string; distance: number } | null = null;
  for (const href of pages) {
    const distance = editDistance(target, href);
    if (!best || distance < best.distance) best = { href, distance };
  }
  if (!best) return null;
  // Distance 0 is a case or trailing-slash slip (Pages is case-sensitive).
  // Otherwise it must be close enough to be a typo, not a different page.
  return best.distance <= Math.max(2, Math.floor(best.href.length / 3)) ? best.href : null;
}

export function DidYouMean() {
  const path = useMissingPath();
  const suggestion = path ? suggestPage(path) : null;
  if (!suggestion) return null;
  return (
    <p className="nf-suggest">
      Did you mean <Link href={suggestion}>{suggestion}</Link>?
    </p>
  );
}
