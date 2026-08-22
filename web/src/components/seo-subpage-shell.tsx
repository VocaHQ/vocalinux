"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SiteChrome } from "@/components/site-chrome";

const pageTitles: Record<string, string> = {
  "/install": "Install Guides",
  "/install/ubuntu": "Ubuntu",
  "/install/fedora": "Fedora",
  "/install/arch": "Arch",
  "/screenshots": "Screenshots",
  "/changelog": "Changelog",
  "/compare": "Engine Comparison",
  "/remote-api": "Remote API",
  "/languages": "Languages",
  "/wayland": "Wayland",
  "/gpu-acceleration": "GPU Acceleration",
  "/voice-activity-detection": "Silero VAD",
  "/advanced-settings": "Advanced Settings",
  "/desktop-reliability": "Desktop Reliability",
  "/autostart": "Autostart",
  "/for-developers": "For Developers",
  "/rsi-prevention": "RSI Prevention",
  "/writers": "For Writers",
  "/gnome-kde": "GNOME vs KDE",
  "/use-cases": "Use Cases",
  "/vs-nerd-dictation": "vs Nerd Dictation",
  "/whisper-model-guide": "Whisper Models",
  "/voice-typing-vscode": "VS Code",
  "/offline": "Offline",
  "/open-source": "Open Source",
  "/privacy": "Privacy Policy",
  "/faq": "FAQ",
  "/troubleshooting": "Troubleshooting",
  "/shortcuts": "Voice Commands",
  "/alternatives": "Alternatives",
};

function titleFromSegment(segment: string): string {
  return segment.replace(/-/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function Breadcrumbs() {
  const pathname = usePathname();
  if (!pathname || pathname === "/") return null;

  const segments = pathname.split("/").filter(Boolean);
  const crumbs = segments.map((segment, index) => {
    const href = "/" + segments.slice(0, index + 1).join("/");
    const key = href.replace(/\/$/, "");
    return {
      href: href.endsWith("/") ? href : `${href}/`,
      label: pageTitles[key] ?? titleFromSegment(segment),
    };
  });

  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link href="/">Home</Link>
      {crumbs.map((crumb, index) => (
        <React.Fragment key={crumb.href}>
          <span aria-hidden="true">/</span>
          {index === crumbs.length - 1 ? (
            <span>{crumb.label}</span>
          ) : (
            <Link href={crumb.href}>{crumb.label}</Link>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}

export function SeoSubpageShell({ children }: { children: React.ReactNode }) {
  return (
    <SiteChrome variant="page">
      <div className="page-main">
        <div className="shell">
          <Breadcrumbs />
          <div className="subpage-content min-w-0">{children}</div>
        </div>
      </div>
    </SiteChrome>
  );
}
