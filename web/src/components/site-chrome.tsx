"use client";

import React, { useEffect, useId, useState } from "react";
import Link from "next/link";
import { Star } from "lucide-react";
import { VocalinuxLogo } from "@/components/optimized-image";
import { GITHUB_REPO_URL, VOCAHQ_URL } from "@/lib/seo";
import {
  footerGroups,
  homeNav,
  mobileExtraNav,
  pageNav,
  socialLinks,
  type NavLink,
} from "@/lib/site-nav";

const GITHUB_API_REPO_URL = `https://api.github.com/repos/${GITHUB_REPO_URL.replace("https://github.com/", "")}`;

function SmartLink({
  href,
  className,
  children,
  onClick,
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
  onClick?: () => void;
}) {
  const external = href.startsWith("http");
  if (external) {
    return (
      <a
        href={href}
        className={className}
        onClick={onClick}
        target="_blank"
        rel="noopener noreferrer"
      >
        {children}
      </a>
    );
  }
  if (href.startsWith("#")) {
    return (
      <a href={href} className={className} onClick={onClick}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={className} onClick={onClick}>
      {children}
    </Link>
  );
}

export function SiteChrome({
  children,
  variant = "page",
}: {
  children: React.ReactNode;
  variant?: "home" | "page";
}) {
  const [open, setOpen] = useState(false);
  const [stars, setStars] = useState<number | null>(null);
  const navId = useId();
  const nav = variant === "home" ? homeNav : pageNav;
  const ctaHref = variant === "home" ? "#install" : "/#install";
  const extras: NavLink[] =
    variant === "home"
      ? [
          { href: "/screenshots/", label: "Screenshots" },
          { href: "/install/", label: "Distro guides" },
          ...mobileExtraNav,
        ]
      : mobileExtraNav;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onResize = () => {
      if (window.innerWidth >= 921) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  useEffect(() => {
    fetch(GITHUB_API_REPO_URL)
      .then((res) => res.json())
      .then((data: { stargazers_count?: number }) => {
        if (data.stargazers_count) setStars(data.stargazers_count);
      })
      .catch(() => setStars(null));
  }, []);

  return (
    <div className="min-h-[100dvh] max-w-[100vw] overflow-x-clip">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="site-header">
        <div className="shell header-inner">
          <Link href="/" className="brand" aria-label="Vocalinux home">
            <VocalinuxLogo width={28} height={28} className="h-7 w-7" />
            <span>Vocalinux</span>
          </Link>

          <nav className="nav-links" aria-label="Primary">
            {nav.map((item) => (
              <SmartLink key={item.href + item.label} href={item.href}>
                {item.label}
              </SmartLink>
            ))}
          </nav>

          <div className="header-actions">
            <a
              className="header-stars"
              href={GITHUB_REPO_URL}
              rel="noopener noreferrer"
              aria-label={
                stars !== null
                  ? `Vocalinux on GitHub, ${stars.toLocaleString()} stars`
                  : "Vocalinux on GitHub"
              }
            >
              <Star
                className="h-4 w-4"
                strokeWidth={1.75}
                fill="currentColor"
                aria-hidden="true"
              />
              <span>{stars !== null ? stars.toLocaleString() : "GitHub"}</span>
            </a>
            <button
              className="nav-toggle"
              type="button"
              aria-expanded={open}
              aria-controls={navId}
              aria-label="Toggle menu"
              onClick={() => setOpen((value) => !value)}
            >
              <span className="sr-only">
                {open ? "Close navigation" : "Open navigation"}
              </span>
              <span className="nav-toggle-bars" aria-hidden="true">
                <i></i>
                <i></i>
                <i></i>
              </span>
            </button>
          </div>
        </div>

        <nav
          id={navId}
          className="mobile-nav shell"
          aria-label="Site"
          hidden={!open}
        >
          {[...nav, ...extras].map((item) => (
            <SmartLink
              key={`m-${item.href}-${item.label}`}
              href={item.href}
              onClick={() => setOpen(false)}
            >
              {item.label}
            </SmartLink>
          ))}
          <a
            className="btn btn-primary"
            href={ctaHref}
            onClick={() => setOpen(false)}
          >
            Install Vocalinux
          </a>
        </nav>
      </header>

      <main id="main">{children}</main>

      <footer className="site-footer">
        <div className="shell">
          <div className="footer-inner">
            <div className="footer-brand">
              <Link href="/" className="brand">
                <VocalinuxLogo width={28} height={28} className="h-7 w-7" />
                <span>Vocalinux</span>
              </Link>
              <p>
                Offline voice typing for Linux. Local engines by default, no
                required account.
              </p>
              <ul className="footer-social">
                {socialLinks.map((item) => (
                  <li key={item.href}>
                    <a
                      href={item.href}
                      {...(item.href.startsWith("http")
                        ? { target: "_blank", rel: "noopener noreferrer" }
                        : {})}
                      aria-label={item.label}
                      title={item.label}
                    >
                      <span
                        className="footer-social-icon"
                        style={{
                          maskImage: `url(${item.icon})`,
                          WebkitMaskImage: `url(${item.icon})`,
                        }}
                      />
                    </a>
                  </li>
                ))}
              </ul>
            </div>
            {footerGroups.map((group) => (
              <div className="footer-col" key={group.title}>
                <h2>{group.title}</h2>
                <ul>
                  {group.links.map((link) => (
                    <li key={link.href + link.label}>
                      <SmartLink href={link.href}>{link.label}</SmartLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="footer-base">
            <span>
              AGPL-3.0. Built in public by{" "}
              <a
                href="https://github.com/jatinkrmalik"
                rel="noopener noreferrer"
              >
                Jatin K Malik
              </a>
              .
            </span>
            <span>
              Part of{" "}
              <a href={VOCAHQ_URL} rel="noopener noreferrer">
                VocaHQ
              </a>
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
