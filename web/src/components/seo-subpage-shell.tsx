"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  Activity,
  Camera,
  ChevronDown,
  ChevronRight,
  Code2,
  Cpu,
  Globe,
  Heart,
  HelpCircle,
  Home,
  Menu,
  Monitor,
  Power,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Shield,
  X,
  Zap,
  Github,
} from "lucide-react";
import { VocalinuxLogo } from "@/components/optimized-image";
import { ThemeToggle } from "@/components/theme-toggle";

interface SeoSubpageShellProps {
  children: React.ReactNode;
}

const navCategories = [
  {
    label: "Get Started",
    items: [
      { href: "/", label: "Home", icon: Home },
      { href: "/install/", label: "Install Guides", icon: BookOpen },
      { href: "/screenshots/", label: "Screenshots", icon: Camera },
      { href: "/changelog/", label: "Changelog", icon: Zap },
    ],
  },
  {
    label: "Features",
    items: [
      { href: "/compare/", label: "Engine Comparison", icon: Cpu },
      { href: "/remote-api/", label: "Remote API", icon: Server },
      { href: "/languages/", label: "Multilingual", icon: Globe },
      { href: "/wayland/", label: "Wayland Support", icon: Monitor },
      { href: "/gpu-acceleration/", label: "GPU Acceleration", icon: Cpu },
      {
        href: "/voice-activity-detection/",
        label: "Silero VAD",
        icon: Activity,
      },
      {
        href: "/advanced-settings/",
        label: "Advanced Settings",
        icon: SlidersHorizontal,
      },
      {
        href: "/desktop-reliability/",
        label: "Desktop Reliability",
        icon: ShieldCheck,
      },
      { href: "/autostart/", label: "Autostart", icon: Power },
    ],
  },
  {
    label: "Use Cases",
    items: [
      { href: "/for-developers/", label: "For Developers", icon: Code2 },
      { href: "/rsi-prevention/", label: "RSI Prevention", icon: Heart },
      { href: "/writers/", label: "For Writers", icon: Heart },
      { href: "/gnome-kde/", label: "GNOME vs KDE", icon: Monitor },
      { href: "/use-cases/", label: "All Use Cases", icon: Zap },
    ],
  },
  {
    label: "Comparisons",
    items: [
      {
        href: "/vs-nerd-dictation/",
        label: "vs Nerd Dictation",
        icon: BookOpen,
      },
      { href: "/whisper-model-guide/", label: "Whisper Models", icon: Cpu },
      { href: "/voice-typing-vscode/", label: "VS Code", icon: Code2 },
    ],
  },
  {
    label: "Privacy & Ethics",
    items: [
      { href: "/offline/", label: "Offline", icon: Shield },
      { href: "/open-source/", label: "Open Source", icon: Code2 },
      { href: "/privacy/", label: "Privacy Policy", icon: Shield },
    ],
  },
  {
    label: "Support",
    items: [
      { href: "/faq/", label: "FAQ", icon: HelpCircle },
      { href: "/troubleshooting/", label: "Troubleshooting", icon: Zap },
      { href: "/shortcuts/", label: "Voice Commands", icon: BookOpen },
      { href: "/alternatives/", label: "Alternatives", icon: BookOpen },
    ],
  },
];

function DropdownMenu({ category }: { category: (typeof navCategories)[0] }) {
  return (
    <div className="group relative">
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:bg-muted focus:text-foreground focus:outline-none"
      >
        {category.label}
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-focus-within:rotate-180 group-hover:rotate-180" />
      </button>

      <div className="pointer-events-none invisible absolute left-0 top-full z-50 mt-0 w-56 rounded-[12px] border border-border bg-background p-1.5 opacity-0 shadow-[0_12px_32px_-12px_rgba(0,0,0,0.35)] transition-all duration-150 group-focus-within:pointer-events-auto group-focus-within:visible group-focus-within:opacity-100 group-hover:pointer-events-auto group-hover:visible group-hover:opacity-100">
        {category.items.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Icon className="h-4 w-4 text-primary" />
              {item.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function Breadcrumbs() {
  const pathname = usePathname();

  if (pathname === "/") return null;

  const segments = pathname.split("/").filter(Boolean);
  const breadcrumbs = segments.map((segment, index) => {
    const href = "/" + segments.slice(0, index + 1).join("/");
    const label = segment
      .replace(/-/g, " ")
      .replace(/\b\w/g, (l) => l.toUpperCase());
    return { href, label };
  });

  const getPageTitle = (path: string): string => {
    for (const category of navCategories) {
      for (const item of category.items) {
        if (item.href === path || item.href === path + "/") {
          return item.label;
        }
      }
    }
    return (
      path
        .split("/")
        .pop()
        ?.replace(/-/g, " ")
        .replace(/\b\w/g, (l) => l.toUpperCase()) || ""
    );
  };

  return (
    <nav className="mb-8 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      <Link href="/" className="transition-colors hover:text-foreground">
        Home
      </Link>
      {breadcrumbs.map((crumb, index) => (
        <React.Fragment key={crumb.href}>
          <ChevronRight className="h-4 w-4 shrink-0" />
          {index === breadcrumbs.length - 1 ? (
            <span className="font-medium text-foreground">
              {getPageTitle(crumb.href)}
            </span>
          ) : (
            <Link
              href={crumb.href}
              className="transition-colors hover:text-foreground"
            >
              {crumb.label}
            </Link>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}

export function SeoSubpageShell({ children }: SeoSubpageShellProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth >= 1024) setMobileMenuOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const mainNavCategories = [
    {
      label: "Get Started",
      items: [
        { href: "/", label: "Home", icon: Home },
        { href: "/install/", label: "Install", icon: BookOpen },
        { href: "/screenshots/", label: "Screenshots", icon: Camera },
        { href: "/changelog/", label: "Changelog", icon: Zap },
      ],
    },
    {
      label: "Features",
      items: [
        { href: "/compare/", label: "Engine Comparison", icon: Cpu },
        { href: "/remote-api/", label: "Remote API", icon: Server },
        { href: "/whisper-model-guide/", label: "Whisper Models", icon: Cpu },
        { href: "/wayland/", label: "Wayland", icon: Monitor },
        { href: "/gpu-acceleration/", label: "GPU Acceleration", icon: Cpu },
        {
          href: "/voice-activity-detection/",
          label: "Silero VAD",
          icon: Activity,
        },
        {
          href: "/advanced-settings/",
          label: "Advanced Settings",
          icon: SlidersHorizontal,
        },
        {
          href: "/desktop-reliability/",
          label: "Reliability",
          icon: ShieldCheck,
        },
      ],
    },
    {
      label: "Use Cases",
      items: [
        { href: "/for-developers/", label: "For Developers", icon: Code2 },
        { href: "/writers/", label: "For Writers", icon: Heart },
        { href: "/voice-typing-vscode/", label: "VS Code", icon: Code2 },
        { href: "/gnome-kde/", label: "GNOME vs KDE", icon: Monitor },
        { href: "/rsi-prevention/", label: "RSI Prevention", icon: Heart },
      ],
    },
    {
      label: "Compare",
      items: [
        {
          href: "/vs-nerd-dictation/",
          label: "vs Nerd Dictation",
          icon: BookOpen,
        },
        { href: "/alternatives/", label: "Alternatives", icon: BookOpen },
        { href: "/offline/", label: "Offline", icon: Shield },
        { href: "/open-source/", label: "Open Source", icon: Code2 },
      ],
    },
    {
      label: "Support",
      items: [
        { href: "/faq/", label: "FAQ", icon: HelpCircle },
        { href: "/troubleshooting/", label: "Troubleshooting", icon: Zap },
        { href: "/shortcuts/", label: "Commands", icon: BookOpen },
        { href: "/privacy/", label: "Privacy Policy", icon: Shield },
      ],
    },
  ];

  return (
    <div className="min-h-screen max-w-[100vw] overflow-x-clip bg-background text-foreground">
      <header className="fixed inset-x-0 top-0 z-50 border-b border-border/80 bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:h-16 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <VocalinuxLogo width={28} height={28} className="h-7 w-7" />
            <span className="font-display text-[15px] font-semibold tracking-tight">
              Vocalinux
            </span>
          </Link>

          <nav className="hidden items-center gap-1 lg:flex">
            {mainNavCategories.map((category) => (
              <DropdownMenu key={category.label} category={category} />
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Link
              href="/#install"
              className="hidden h-9 items-center rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground sm:inline-flex"
            >
              Install
            </Link>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setMobileMenuOpen(!mobileMenuOpen);
              }}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:hidden"
              aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
              aria-expanded={mobileMenuOpen}
            >
              {mobileMenuOpen ? (
                <X className="h-5 w-5" />
              ) : (
                <Menu className="h-5 w-5" />
              )}
            </button>
          </div>
        </div>

        {mobileMenuOpen ? (
          <div className="border-t border-border bg-background lg:hidden">
            <nav className="max-h-[calc(100vh-4rem)] overflow-y-auto px-4 py-4">
              {mainNavCategories.map((category) => (
                <div key={category.label} className="mb-4">
                  <h3 className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {category.label}
                  </h3>
                  <div className="space-y-0.5">
                    {category.items.map((item) => {
                      const Icon = item.icon;
                      return (
                        <Link
                          key={item.href}
                          href={item.href}
                          onClick={() => setMobileMenuOpen(false)}
                          className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        >
                          <Icon className="h-4 w-4 text-primary" />
                          {item.label}
                        </Link>
                      );
                    })}
                  </div>
                </div>
              ))}
              <Link
                href="/#install"
                onClick={() => setMobileMenuOpen(false)}
                className="mt-2 flex items-center justify-center rounded-full bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
              >
                Install Vocalinux
              </Link>
            </nav>
          </div>
        ) : null}
      </header>

      <div className="mx-auto w-full max-w-6xl px-4 pb-16 pt-24 sm:px-6 sm:pt-28">
        <Breadcrumbs />
        <div className="subpage-content min-w-0">{children}</div>
      </div>

      <footer className="border-t border-border bg-[#0a0a0c] text-zinc-300">
        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
          <div className="mb-8 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <p className="text-sm font-semibold text-zinc-100">
                Want the full product overview?
              </p>
              <p className="mt-1 text-sm text-zinc-400">
                Homepage has the install command, app screenshots, and engine
                guide.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
              >
                Home
                <ChevronRight className="h-4 w-4" />
              </Link>
              <Link
                href="/#install"
                className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-100 transition-colors hover:border-zinc-500"
              >
                Install
              </Link>
              <a
                href="https://github.com/VocaHQ/vocalinux"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-100 transition-colors hover:border-zinc-500"
              >
                <Github className="h-4 w-4" />
                GitHub
              </a>
            </div>
          </div>

          <div className="grid gap-6 border-t border-zinc-800 pt-8 sm:grid-cols-2 lg:grid-cols-5">
            {mainNavCategories.map((category) => (
              <div key={category.label}>
                <h4 className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                  {category.label}
                </h4>
                <ul className="space-y-1.5">
                  {category.items.map((item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className="text-sm text-zinc-400 transition-colors hover:text-white"
                      >
                        {item.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="mt-8 border-t border-zinc-800 pt-6 text-sm text-zinc-500">
            Vocalinux is part of{" "}
            <a
              href="https://vocahq.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-zinc-400 transition-colors hover:text-white"
            >
              VocaHQ
            </a>
            .
          </p>
        </div>
      </footer>
    </div>
  );
}
