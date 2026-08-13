"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Check,
  ChevronRight,
  Copy,
  Github,
  Menu,
  Star,
  Terminal,
  X,
  Heart,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { VocalinuxLogo } from "@/components/optimized-image";
import { ThemeScreenshotImage } from "@/components/theme-screenshot";

// Always uses main/install.sh. The installer dynamically resolves the latest release tag via GitHub API
const installCommands = {
  interactiveInstallCommand: `curl -fsSL https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/install.sh -o /tmp/vl.sh && bash /tmp/vl.sh --interactive`,
  interactiveInstallDisplayCommand: `curl -fsSL \\
  https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/install.sh \\
  -o /tmp/vl.sh && \\
bash /tmp/vl.sh --interactive`,
  uninstallCommand: `curl -fsSL https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/uninstall.sh -o /tmp/vul.sh && bash /tmp/vul.sh`,
  uninstallDisplayCommand: `curl -fsSL \\
  https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/uninstall.sh \\
  -o /tmp/vul.sh && \\
bash /tmp/vul.sh`,
};

const homeJsonLd = [
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "@id": "https://vocalinux.com/#softwareapplication",
    name: "Vocalinux",
    applicationCategory: "UtilitiesApplication",
    operatingSystem: "Linux",
    isAccessibleForFree: true,
    license: "https://github.com/jatinkrmalik/vocalinux/blob/main/LICENSE",
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "USD",
    },
    description:
      "Offline voice dictation and speech-to-text for Linux with whisper.cpp and VOSK.",
    softwareVersion: "0.15.0",
    author: {
      "@type": "Person",
      name: "Jatin K Malik",
      url: "https://github.com/jatinkrmalik",
    },
    url: "https://vocalinux.com/",
    downloadUrl: "https://github.com/jatinkrmalik/vocalinux",
    screenshot: "https://vocalinux.com/og-image.png",
    featureList: [
      "100% offline speech recognition",
      "Remote API speech recognition for compatible self-hosted transcription servers",
      "Silero neural voice activity detection with amplitude fallback",
      "Works with X11 and Wayland",
      "Toggle and push-to-talk shortcut modes",
      "Left/right modifier key distinction for shortcuts",
      "Optional voice commands with VOSK-aware defaults",
      "Searchable sidebar settings",
      "AppImage packages for x86_64 and aarch64",
      "Expanded speech-language catalog including Hungarian (per-engine availability)",
      "Auto-capitalize sentences after punctuation",
      "Trailing space after completed transcriptions for continuous dictation",
      "Auto-pause competing apps and idle model keep-alive unload",
      "Vulkan discrete GPU auto-select with manual device selection",
      "IBus via ibus-wayland on compositors that previously skipped IBus",
      "Adaptive audio and IBus-aware text injection",
      "Clipboard fallback for unsupported Wayland compositors",
      "Sound effects toggle for audio feedback",
      "whisper.cpp, Whisper, VOSK, and Remote API support",
      "Advanced whisper.cpp anti-hallucination settings",
      "Auto-recover speech recognition after system suspend/resume",
      "Safe engine switching without segfaults",
      "Keyboard layout preserved during IBus activation",
      "IBus runtime recovery and non-ASCII text injection fallback",
      "Push-to-talk mode with improved silence detection",
      "Linux desktop integration",
    ],
  },
  {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: [
      {
        "@type": "Question",
        name: "Is Vocalinux really 100% offline?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Yes for local engines. All local speech recognition runs on your Linux machine. Vocalinux also offers an optional Remote API engine for user-configured servers.",
        },
      },
      {
        "@type": "Question",
        name: "Does Vocalinux collect usage telemetry?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "No. The installed app does not send usage telemetry, analytics events, or background usage pings. Even the project maintainer cannot see how many people install or actively use Vocalinux.",
        },
      },
      {
        "@type": "Question",
        name: "Which Linux distributions are supported?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Vocalinux supports Ubuntu, Fedora, Debian, Arch, Linux Mint, Pop!_OS, and other modern Linux distributions across X11 and Wayland.",
        },
      },
      {
        "@type": "Question",
        name: "How do I switch between speech engines?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Use the settings GUI or CLI flags for whisper.cpp, Whisper, VOSK, or Remote API. Open Settings from the tray and use the sidebar (search works). Remote API options live under Advanced.",
        },
      },
      {
        "@type": "Question",
        name: "What happens when I close my laptop lid?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Vocalinux v0.10.1+ automatically recovers speech recognition and keyboard shortcuts after system suspend/resume. No manual restart needed.",
        },
      },
      {
        "@type": "Question",
        name: "Does Vocalinux preserve my keyboard layout?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Yes. v0.10.1+ preserves your XKB keyboard layout when activating IBus, so you won't unexpectedly switch to US layout mid-dictation.",
        },
      },
    ],
  },
  {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: "Install Vocalinux on Linux",
    description: "Install offline voice dictation on Linux in a few minutes.",
    totalTime: "PT10M",
    step: [
      {
        "@type": "HowToStep",
        name: "Run the install command",
        text: "Copy the install command from vocalinux.com and run it in terminal.",
        url: "https://vocalinux.com/#install",
      },
      {
        "@type": "HowToStep",
        name: "Complete the guided setup",
        text: "Pick your speech engine and model size in the interactive installer.",
        url: "https://vocalinux.com/#install",
      },
      {
        "@type": "HowToStep",
        name: "Start dictating",
        text: "Launch vocalinux and hold Right Alt (Option) to begin dictation, or choose toggle mode in Settings.",
        url: "https://vocalinux.com/#install",
      },
    ],
  },
];

const featureRows = [
  {
    title: "Stays on your machine",
    body: "Local engines process audio on-device. No cloud upload, no telemetry, no account.",
    href: "/offline/",
    link: "Offline privacy",
  },
  {
    title: "Works where you type",
    body: "Terminals, browsers, IDEs, office apps, and any focused text field on X11 or Wayland.",
    href: "/use-cases/",
    link: "Use cases",
  },
  {
    title: "Fast by default",
    body: "whisper.cpp with Vulkan on AMD, Intel, and NVIDIA. Tiny model is about 74MB.",
    href: "/gpu-acceleration/",
    link: "GPU acceleration",
  },
  {
    title: "Your shortcuts",
    body: "Toggle or push-to-talk. Bind modifiers the way your hands already work.",
    href: "/shortcuts/",
    link: "Shortcuts",
  },
  {
    title: "Desktop reliability",
    body: "Suspend recovery, IBus hardening, layout preservation, non-ASCII injection fallbacks.",
    href: "/desktop-reliability/",
    link: "Reliability notes",
  },
  {
    title: "Neural silence filter",
    body: "Silero VAD drops empty buffers before recognition, with amplitude fallback if needed.",
    href: "/voice-activity-detection/",
    link: "Voice activity detection",
  },
];

const engines = [
  {
    name: "whisper.cpp",
    badge: "Default",
    summary: "C++ Whisper with Vulkan. Fast install, multi-vendor GPU.",
    points: [
      "About 1–2 min default setup",
      "AMD / Intel / NVIDIA via Vulkan",
      "Tiny model ~74MB",
    ],
  },
  {
    name: "Whisper",
    summary: "Original OpenAI PyTorch path for NVIDIA CUDA workflows.",
    points: [
      "Same model family accuracy",
      "CUDA when you already live in PyTorch",
      "Larger install footprint",
    ],
  },
  {
    name: "VOSK",
    summary: "Small footprint for older machines and tight RAM budgets.",
    points: [
      "CPU-friendly streaming",
      "Models around ~40MB",
      "Great on modest hardware",
    ],
  },
  {
    name: "Remote API",
    summary: "Offload to a server you trust while keeping desktop injection local.",
    points: [
      "OpenAI-compatible endpoints",
      "whisper.cpp server support",
      "Local VAD still applies",
    ],
  },
];

const CopyButton = ({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) => {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? "Copied" : "Copy"}
      className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-600 ${
        copied ? "text-[color:var(--terminal-fg)] hover:text-[color:var(--terminal-fg)]" : ""
      } ${className}`}
      aria-label={copied ? "Copied to clipboard" : "Copy to clipboard"}
    >
      {copied ? (
        <Check className="h-4 w-4" strokeWidth={2} />
      ) : (
        <Copy className="h-4 w-4" strokeWidth={1.75} />
      )}
    </button>
  );
};

function TerminalBlock({
  command,
  displayCommand,
  label = "terminal",
}: {
  command: string;
  displayCommand: string;
  label?: string;
}) {
  return (
    <div className="terminal-panel">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex gap-1.5" aria-hidden>
            <span className="h-2.5 w-2.5 rounded-full bg-zinc-700" />
            <span className="h-2.5 w-2.5 rounded-full bg-zinc-700" />
            <span className="h-2.5 w-2.5 rounded-full bg-zinc-700" />
          </div>
          <span className="truncate font-mono text-[11px] tracking-wide text-zinc-500">
            {label}
          </span>
        </div>
        <CopyButton text={command} />
      </div>
      <div className="min-w-0 max-w-full overflow-x-auto p-4 sm:p-5">
        <pre className="max-w-full whitespace-pre-wrap break-all text-left font-mono text-[13px] leading-relaxed text-[color:var(--terminal-fg)] sm:text-sm">
          <span className="select-none text-zinc-600">$ </span>
          {displayCommand}
        </pre>
      </div>
    </div>
  );
}

export default function HomePage() {
  const [stars, setStars] = useState<number | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    fetch("https://api.github.com/repos/jatinkrmalik/vocalinux")
      .then((res) => res.json())
      .then((data) => {
        if (data.stargazers_count) setStars(data.stargazers_count);
      })
      .catch(() => setStars(null));
  }, []);

  const navLinks = [
    { href: "#features", label: "Features" },
    { href: "/screenshots/", label: "Screenshots" },
    { href: "#install", label: "Install" },
    { href: "#guides", label: "Guides" },
    { href: "#faq", label: "FAQ" },
  ];

  const {
    interactiveInstallCommand,
    interactiveInstallDisplayCommand,
    uninstallCommand,
    uninstallDisplayCommand,
  } = installCommands;

  return (
    <main className="min-h-screen max-w-[100vw] overflow-x-clip bg-background text-foreground">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(homeJsonLd) }}
      />

      <header className="fixed inset-x-0 top-0 z-50 border-b border-border/80 bg-background/85 backdrop-blur-md">
        <nav className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:h-16 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <VocalinuxLogo width={28} height={28} className="h-7 w-7" priority />
            <span className="font-display text-[15px] font-semibold tracking-tight">
              Vocalinux
            </span>
          </Link>

          <div className="hidden items-center gap-7 md:flex">
            {navLinks.map((link) =>
              link.href.startsWith("/") ? (
                <Link
                  key={link.href}
                  href={link.href}
                  className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                  {link.label}
                </Link>
              ) : (
                <a
                  key={link.href}
                  href={link.href}
                  className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                  {link.label}
                </a>
              ),
            )}
            <a
              href="https://github.com/jatinkrmalik/vocalinux"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <Star className="h-3.5 w-3.5 fill-current" />
              {stars !== null ? stars.toLocaleString() : "GitHub"}
            </a>
            <ThemeToggle />
            <a href="#install" className="inline-flex h-9 items-center rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground">
              Install
            </a>
          </div>

          <div className="flex items-center gap-2 md:hidden">
            <ThemeToggle />
            <button
              type="button"
              onClick={() => setMobileMenuOpen((v) => !v)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border"
              aria-label="Toggle menu"
              aria-expanded={mobileMenuOpen}
            >
              {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </nav>

        {mobileMenuOpen ? (
          <div className="border-t border-border bg-background px-4 py-3 md:hidden">
            <div className="flex flex-col gap-1">
              {navLinks.map((link) =>
                link.href.startsWith("/") ? (
                  <Link
                    key={link.href}
                    href={link.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className="rounded-md px-2 py-2.5 text-sm font-medium"
                  >
                    {link.label}
                  </Link>
                ) : (
                  <a
                    key={link.href}
                    href={link.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className="rounded-md px-2 py-2.5 text-sm font-medium"
                  >
                    {link.label}
                  </a>
                ),
              )}
              <a
                href="https://github.com/jatinkrmalik/vocalinux"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-md px-2 py-2.5 text-sm font-medium"
              >
                <Github className="h-4 w-4" />
                GitHub
              </a>
              <a
                href="#install"
                onClick={() => setMobileMenuOpen(false)}
                className="mt-1 rounded-full bg-primary px-3 py-2.5 text-center text-sm font-medium text-primary-foreground"
              >
                Install
              </a>
            </div>
          </div>
        ) : null}
      </header>

      {/* Hero: asymmetric copy + real screenshot (from PR #546 language) */}
      <section className="relative overflow-hidden px-4 pb-16 pt-24 sm:px-6 sm:pb-20 sm:pt-28">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.55] dark:opacity-40"
          aria-hidden
          style={{
            background:
              "radial-gradient(60% 50% at 85% 20%, color-mix(in oklab, var(--primary) 18%, transparent), transparent 70%)",
          }}
        />
        <div className="relative mx-auto grid max-w-6xl min-w-0 items-center gap-10 lg:grid-cols-12 lg:gap-12">
          <div className="min-w-0 lg:col-span-6">
            <p className="mb-5 font-mono text-[12px] uppercase tracking-[0.16em] text-primary">
              Offline on Linux
            </p>
            <h1 className="font-display max-w-[14ch] text-[2.35rem] font-semibold leading-[1.08] tracking-[-0.03em] sm:text-5xl lg:text-[3.35rem]">
              Dictate into any app. Keep the audio home.
            </h1>
            <p className="mt-5 max-w-[36ch] text-base leading-relaxed text-muted-foreground sm:text-lg">
              System-wide voice typing with local models. X11 and Wayland. One
              install command.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              <a href="#install" className="btn-primary w-full sm:w-auto">
                Install Vocalinux
              </a>
              <a
                href="https://github.com/jatinkrmalik/vocalinux"
                target="_blank"
                rel="noopener noreferrer"
                className="btn-secondary w-full sm:w-auto"
              >
                <Github className="h-4 w-4" />
                Source
              </a>
              <a href="#ecosystem" className="btn-ghost w-full sm:w-auto">
                macOS / Windows
              </a>
            </div>
            <dl className="mt-10 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-border pt-6 sm:grid-cols-4">
              {[
                ["Offline", "Local engines"],
                ["Display", "X11 + Wayland"],
                ["Default", "whisper.cpp"],
                ["License", "AGPL-3.0"],
              ].map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                    {k}
                  </dt>
                  <dd className="mt-1 text-sm font-medium">{v}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="min-w-0 lg:col-span-6">
            <div className="relative">
              <div
                className="absolute -inset-3 rounded-2xl bg-primary/10 blur-2xl dark:bg-primary/15"
                aria-hidden
              />
              <figure className="shot-frame relative">
                <ThemeScreenshotImage
                  src="/screenshots/00-transcription.png"
                  srcDark="/screenshots/dark/00-transcription.png"
                  alt="Vocalinux dictating into a text editor with the tray menu open"
                  width={2518}
                  height={2057}
                  priority
                  className="h-auto w-full"
                />
                <figcaption className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-muted-foreground">
                  <span>Dictation into any focused app</span>
                  <Link
                    href="/screenshots/"
                    className="inline-flex items-center gap-1 font-medium text-foreground hover:text-primary"
                  >
                    More shots
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Link>
                </figcaption>
              </figure>
            </div>
          </div>
        </div>
      </section>

      {/* Full-bleed install strip */}
      <section
        id="install"
        className="border-y border-border bg-[#0a0a0c] px-4 py-14 text-zinc-100 sm:px-6 sm:py-16"
      >
        <div className="mx-auto max-w-6xl min-w-0">
          <div className="mb-8 grid gap-4 lg:grid-cols-12 lg:items-end">
            <div className="min-w-0 lg:col-span-7">
              <h2 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
                Install in one command
              </h2>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-zinc-400 sm:text-base">
                Interactive installer detects hardware, lets you pick an engine,
                and wires the desktop app.
              </p>
            </div>
            <p className="font-mono text-xs text-zinc-400 lg:col-span-5 lg:text-right">
              Ubuntu · Fedora · Debian · Arch · openSUSE
            </p>
          </div>
          <TerminalBlock
            command={interactiveInstallCommand}
            displayCommand={interactiveInstallDisplayCommand}
            label="install.sh --interactive"
          />
          <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm text-zinc-300">
            <span>
              Then launch:{" "}
              <code className="font-mono text-emerald-400">vocalinux</code>
            </span>
            <a
              href="https://github.com/jatinkrmalik/vocalinux/releases"
              className="text-zinc-100 underline-offset-4 hover:underline"
            >
              AppImage downloads
            </a>
            <Link
              href="/compare/"
              className="text-zinc-100 underline-offset-4 hover:underline"
            >
              Compare engines
            </Link>
            <Link
              href="/install/"
              className="text-zinc-100 underline-offset-4 hover:underline"
            >
              Distro notes
            </Link>
          </div>
        </div>
      </section>

      {/* Features bento + screenshots */}
      <section
        id="features"
        className="border-t border-border bg-card/40 px-4 py-16 sm:px-6 sm:py-20"
      >
        <div className="mx-auto max-w-6xl min-w-0">
          <div className="mb-10 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="section-heading">Built for real Linux desktops</h2>
              <p className="section-lede">
                Privacy, injection reliability, and engines that match your
                hardware, not a cloud dashboard with a mic icon.
              </p>
            </div>
            <Link
              href="/screenshots/"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              App screenshots
              <ChevronRight className="h-4 w-4" />
            </Link>
          </div>

          {/*
            Paired layout: settings shot stretches with the feature rail.
            object-contain keeps the full dialog visible (no side crop).
          */}
          <div className="grid items-stretch gap-5 lg:grid-cols-12 lg:gap-6">
            <figure className="shot-frame flex h-full min-h-0 flex-col lg:col-span-7">
              <div className="relative min-h-[16rem] flex-1 overflow-hidden bg-zinc-950 sm:min-h-[18rem]">
                <ThemeScreenshotImage
                  src="/screenshots/settings-speech-engine.png"
                  srcDark="/screenshots/dark/settings-speech-engine.png"
                  alt="Vocalinux settings dialog showing speech engine options"
                  width={2128}
                  height={1698}
                  className="absolute inset-0 h-full w-full object-contain p-2 sm:p-3"
                />
              </div>
              <figcaption className="shrink-0 border-t border-border px-4 py-2.5 text-sm text-muted-foreground">
                Engine and model controls in the settings GUI
              </figcaption>
            </figure>

            <div className="flex h-full min-w-0 flex-col overflow-hidden rounded-[12px] border border-border bg-background lg:col-span-5">
              {featureRows.map((f, i) => (
                <Link
                  key={f.title}
                  href={f.href}
                  className={`group flex min-w-0 flex-1 flex-col justify-center px-4 py-3 transition-colors hover:bg-muted/50 sm:px-5 sm:py-3.5 ${
                    i > 0 ? "border-t border-border" : ""
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-[15px] font-semibold leading-snug">
                      {f.title}
                    </h3>
                    <ChevronRight className="h-4 w-4 shrink-0 text-primary opacity-70 transition-transform group-hover:translate-x-0.5 group-hover:opacity-100" />
                  </div>
                  <p className="mt-1 text-sm leading-snug text-muted-foreground">
                    {f.body}
                  </p>
                  <span className="mt-1 text-xs font-medium text-primary">
                    {f.link}
                  </span>
                </Link>
              ))}
            </div>
          </div>

          <div className="mt-5 grid items-stretch gap-5 lg:grid-cols-12 lg:gap-6">
            <figure className="shot-frame lg:col-span-5">
              <ThemeScreenshotImage
                src="/screenshots/02-system-tray.png"
                srcDark="/screenshots/dark/02-system-tray.png"
                alt="Vocalinux system tray icon and menu"
                width={315}
                height={466}
                className="mx-auto h-auto max-h-[18rem] w-auto object-contain sm:max-h-[20rem]"
              />
              <figcaption className="border-t border-border px-4 py-2.5 text-sm text-muted-foreground">
                Tray status while you work
              </figcaption>
            </figure>

            <div className="flex flex-col justify-center rounded-[12px] border border-border bg-background p-5 sm:p-6 lg:col-span-7">
              <h3 className="font-display text-xl font-semibold tracking-tight sm:text-2xl">
                The Linux voice gap, closed
              </h3>
              <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground sm:text-base">
                macOS and Windows shipped system dictation years ago. Linux
                users got fragments. Vocalinux is the full desktop path: tray,
                hotkeys, injection, and local models.
              </p>
              <ul className="mt-5 grid gap-2 sm:grid-cols-2">
                {[
                  "No cloud dependency for local engines",
                  "Works across apps, not one editor",
                  "Guided install, not a research project",
                  "Open source you can audit",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="px-4 py-16 sm:px-6 sm:py-20">
        <div className="mx-auto max-w-6xl min-w-0">
          <h2 className="section-heading">From install to first sentence</h2>
          <ol className="mt-10 grid gap-0 border-t border-border md:grid-cols-3">
            {[
              {
                n: "1",
                title: "Run the installer",
                body: "One curl. It pulls dependencies, models, and desktop integration.",
              },
              {
                n: "2",
                title: "Pick an engine",
                body: "Default whisper.cpp, or Whisper, VOSK, or a remote server you control.",
              },
              {
                n: "3",
                title: "Hold or toggle",
                body: "Activate the shortcut, speak, and text lands in the focused field.",
              },
            ].map((step) => (
              <li
                key={step.n}
                className="border-b border-border py-8 md:border-b-0 md:border-r md:px-6 md:py-10 md:first:pl-0 md:last:border-r-0 md:last:pr-0"
              >
                <span className="font-mono text-sm text-primary">{step.n}</span>
                <h3 className="mt-3 text-xl font-semibold">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {step.body}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Install details */}
      <section className="border-t border-border bg-card/40 px-4 py-16 sm:px-6 sm:py-20">
        <div className="mx-auto max-w-6xl min-w-0">
          <div className="grid gap-10 lg:grid-cols-12 lg:items-start">
            <div className="lg:col-span-5">
              <h2 className="section-heading">What the installer does</h2>
              <ul className="mt-6 space-y-3 text-sm text-muted-foreground">
                {[
                  "Installs system dependencies",
                  "Creates an isolated virtual environment",
                  "Downloads speech models for your choice",
                  "Sets up desktop integration and PATH",
                  "Creates an application launcher",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div className="min-w-0 lg:col-span-7">
              <h3 className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                Uninstall
              </h3>
              <TerminalBlock
                command={uninstallCommand}
                displayCommand={uninstallDisplayCommand}
                label="uninstall.sh"
              />
            </div>
          </div>

          {/* Spec rail — label/value pairs, not a nested bullet card */}
          <div className="mt-12 border-t border-border pt-10">
            <h3 className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              System requirements
            </h3>
            <dl className="mt-6 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-5">
              {[
                {
                  label: "OS",
                  value: "Ubuntu, Debian, Fedora, Arch, openSUSE, or equivalent",
                },
                {
                  label: "Runtime",
                  value: "Python 3.9+ with GTK 3 / PyGObject",
                },
                {
                  label: "Memory",
                  value: "4GB minimum; 8GB+ for larger models",
                },
                {
                  label: "Display",
                  value: "Microphone plus X11 or Wayland session",
                },
                {
                  label: "Disk",
                  value: "~200MB for the default whisper.cpp setup",
                },
              ].map((row) => (
                <div key={row.label} className="min-w-0 border-l border-border pl-4">
                  <dt className="font-mono text-[11px] uppercase tracking-wider text-primary">
                    {row.label}
                  </dt>
                  <dd className="mt-1.5 text-sm leading-snug text-foreground">
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>

      {/* Distro guides */}
      <section id="guides" className="px-4 py-16 sm:px-6 sm:py-20">
        <div className="mx-auto max-w-6xl min-w-0">
          <h2 className="section-heading">Guides by distribution</h2>
          <p className="section-lede">
            Distro-specific notes for Ubuntu, Fedora, and Arch, including
            post-install checks.
          </p>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {[
              {
                href: "/install/ubuntu/",
                title: "Ubuntu",
                description: "Ubuntu 22.04+ for GNOME, KDE, X11, and Wayland.",
              },
              {
                href: "/install/fedora/",
                title: "Fedora",
                description: "Fedora Workstation setup with distro-specific notes.",
              },
              {
                href: "/install/arch/",
                title: "Arch",
                description: "Arch, Manjaro, and EndeavourOS with injection checks.",
              },
            ].map((guide) => (
              <Link
                key={guide.href}
                href={guide.href}
                className="group rounded-[12px] border border-border bg-background p-5 transition-colors hover:border-primary/40"
              >
                <h3 className="text-lg font-semibold group-hover:text-primary">
                  {guide.title}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  {guide.description}
                </p>
                <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-primary">
                  Read guide <ChevronRight className="h-4 w-4" />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Engines */}
      <section className="border-t border-border bg-card/40 px-4 py-16 sm:px-6 sm:py-20">
        <div className="mx-auto max-w-6xl min-w-0">
          <h2 className="section-heading">Speech engines</h2>
          <p className="section-lede">
            Local engines process audio on-device. Remote API is optional for a
            server you control.
          </p>
          <div className="mt-10 divide-y divide-border rounded-[12px] border border-border bg-background">
            {engines.map((engine) => (
              <div
                key={engine.name}
                className="grid gap-3 p-5 sm:grid-cols-[13rem_minmax(0,1fr)] sm:items-center sm:gap-8"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
                  <h3 className="font-semibold leading-none">{engine.name}</h3>
                  {engine.badge ? (
                    <span className="inline-flex items-center rounded-md border border-primary/25 bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider text-primary">
                      {engine.badge}
                    </span>
                  ) : null}
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-muted-foreground">{engine.summary}</p>
                  <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
                    {engine.points.map((p) => (
                      <li key={p} className="inline-flex items-center gap-1.5">
                        <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
                        {p}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-6">
            <Link
              href="/compare/"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              Full engine comparison <ChevronRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="px-4 py-16 sm:px-6 sm:py-20">
        <div className="mx-auto max-w-3xl min-w-0">
          <h2 className="section-heading mb-8">FAQ</h2>
          <div className="space-y-3">
            {(
              [
                {
                  question: "Is Vocalinux really 100% offline?",
                  answer: (
                    <>
                      Yes for local engines: whisper.cpp, Whisper, and VOSK
                      process speech on your machine. Remote API is optional and
                      only talks to servers you configure.{" "}
                      <Link href="/offline/" className="font-medium text-primary hover:underline">
                        Offline details
                      </Link>
                      .
                    </>
                  ),
                },
                {
                  question: "Does Vocalinux collect usage telemetry?",
                  answer:
                    "No. The installed app does not send usage telemetry, analytics events, or background usage pings.",
                },
                {
                  question: "Which Linux distributions are supported?",
                  answer: (
                    <>
                      Ubuntu 22.04+, Debian 11+, Fedora 39+, Arch, openSUSE
                      Tumbleweed, and most modern desktops on X11 or Wayland.{" "}
                      <Link href="/install/" className="font-medium text-primary hover:underline">
                        Install guides
                      </Link>
                      .
                    </>
                  ),
                },
                {
                  question: "How do I switch between speech engines?",
                  answer: (
                    <>
                      Settings dialog or CLI:{" "}
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]">
                        --engine whisper_cpp
                      </code>
                      ,{" "}
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]">
                        whisper
                      </code>
                      ,{" "}
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]">
                        vosk
                      </code>
                      , or{" "}
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]">
                        remote_api
                      </code>
                      .{" "}
                      <Link href="/compare/" className="font-medium text-primary hover:underline">
                        Compare engines
                      </Link>
                      .
                    </>
                  ),
                },
                {
                  question: "Can Vocalinux use a remote transcription server?",
                  answer: (
                    <>
                      Yes. OpenAI-compatible Whisper servers and the whisper.cpp
                      server endpoint under Settings → Advanced → Remote Server.{" "}
                      <Link href="/remote-api/" className="font-medium text-primary hover:underline">
                        Remote API guide
                      </Link>
                      .
                    </>
                  ),
                },
                {
                  question: "What happens when I close my laptop lid?",
                  answer: (
                    <>
                      v0.10.1+ recovers speech recognition and shortcuts after
                      suspend/resume.{" "}
                      <Link href="/desktop-reliability/" className="font-medium text-primary hover:underline">
                        Reliability notes
                      </Link>
                      .
                    </>
                  ),
                },
                {
                  question: "Does Vocalinux preserve my keyboard layout?",
                  answer:
                    "Yes. v0.10.1+ keeps your XKB layout when activating IBus.",
                },
                {
                  question: "Is Vocalinux free?",
                  answer: (
                    <>
                      Yes. AGPL-3.0, no premium tiers.{" "}
                      <Link href="/open-source/" className="font-medium text-primary hover:underline">
                        About the project
                      </Link>
                      .
                    </>
                  ),
                },
              ] as { question: string; answer: React.ReactNode }[]
            ).map((item) => (
              <details
                key={item.question}
                className="group rounded-[12px] border border-border bg-background"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 p-5">
                  <h3 className="pr-2 font-semibold">{item.question}</h3>
                  <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
                </summary>
                <div className="px-5 pb-5 text-muted-foreground">{item.answer}</div>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Ecosystem */}
      <section
        id="ecosystem"
        className="border-t border-border bg-card/40 px-4 py-16 sm:px-6 sm:py-20"
      >
        <div className="mx-auto max-w-6xl min-w-0">
          <h2 className="section-heading">Voca on other platforms</h2>
          <p className="section-lede">
            Related projects for macOS and Windows. This site is about the Linux
            app.
          </p>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {[
              {
                name: "VocaMac",
                status: "Beta",
                body: "Native macOS menu bar app. Offline voice-to-text with WhisperKit and CoreML.",
                site: "https://vocamac.com",
                gh: "https://github.com/jatinkrmalik/vocamac",
                primary: false,
              },
              {
                name: "VocaLinux",
                status: "You are here",
                body: "System tray app with whisper.cpp, Vulkan, and full offline support on Linux.",
                site: "#install",
                gh: "https://github.com/jatinkrmalik/vocalinux",
                primary: true,
              },
              {
                name: "VocaWin",
                status: "Planned",
                body: "Windows tray app with an offline-first design. Still in planning.",
                site: "https://vocawin.com",
                gh: "https://github.com/jatinkrmalik/vocawin",
                primary: false,
              },
            ].map((item) => (
              <div
                key={item.name}
                className={`rounded-[12px] border bg-background p-5 ${
                  item.primary ? "border-2 border-primary" : "border-border"
                }`}
              >
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h3 className="text-lg font-semibold">{item.name}</h3>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      item.primary
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {item.status}
                  </span>
                </div>
                <p className="mb-4 text-sm text-muted-foreground">{item.body}</p>
                <div className="flex flex-wrap gap-2">
                  <a
                    href={item.site}
                    target={item.site.startsWith("http") ? "_blank" : undefined}
                    rel={item.site.startsWith("http") ? "noopener noreferrer" : undefined}
                    className="inline-flex items-center rounded-full bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
                  >
                    {item.primary ? "Install" : "Website"}
                  </a>
                  <a
                    href={item.gh}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center rounded-full border border-border px-3 py-2 text-sm font-medium"
                  >
                    GitHub
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-border px-4 py-16 sm:px-6 sm:py-20">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="section-heading">Install and try a real dictation session</h2>
          <p className="section-lede mx-auto">
            Free under AGPL-3.0. Local engines by default. Star the repo if it
            helps your setup.
          </p>
          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <a href="#install" className="btn-primary">
              Install Vocalinux
            </a>
            <a
              href="https://github.com/jatinkrmalik/vocalinux"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary"
            >
              <Star className="h-4 w-4" />
              Star on GitHub
            </a>
          </div>
        </div>
      </section>

      <footer className="border-t border-border bg-[#0a0a0c] px-4 py-12 text-zinc-300 sm:px-6 dark:bg-card">
        <div className="mx-auto max-w-6xl">
          <div className="mb-12 grid grid-cols-2 gap-8 md:grid-cols-3 lg:grid-cols-6">
            <div className="col-span-2 mb-4 lg:col-span-1 lg:mb-0">
              <Link href="/" className="mb-4 flex items-center gap-2">
                <VocalinuxLogo width={32} height={32} className="h-8 w-8" />
                <span className="font-display text-xl font-semibold text-white">
                  Vocalinux
                </span>
              </Link>
              <p className="mb-4 max-w-xs text-sm text-zinc-400">
                Free open-source voice dictation for Linux. Offline by default.
              </p>
              <a
                href="https://github.com/jatinkrmalik/vocalinux"
                target="_blank"
                rel="noopener noreferrer"
                className="text-zinc-400 transition-colors hover:text-white"
                aria-label="GitHub"
              >
                <Github className="h-6 w-6" />
              </a>
            </div>
            {(
              [
                {
                  title: "Get started",
                  links: [
                    { href: "#features", label: "Features" },
                    { href: "/install/", label: "Install guide" },
                    { href: "/screenshots/", label: "Screenshots" },
                    { href: "/changelog/", label: "Changelog" },
                  ],
                },
                {
                  title: "Recognition",
                  links: [
                    { href: "/compare/", label: "Engine comparison" },
                    { href: "/remote-api/", label: "Remote API" },
                    { href: "/whisper-model-guide/", label: "Whisper models" },
                    { href: "/advanced-settings/", label: "Advanced settings" },
                  ],
                },
                {
                  title: "Desktop",
                  links: [
                    { href: "/wayland/", label: "Wayland" },
                    { href: "/gpu-acceleration/", label: "GPU acceleration" },
                    { href: "/desktop-reliability/", label: "Reliability" },
                    { href: "/offline/", label: "Offline" },
                  ],
                },
                {
                  title: "Use cases",
                  links: [
                    { href: "/for-developers/", label: "Developers" },
                    { href: "/writers/", label: "Writers" },
                    { href: "/voice-typing-vscode/", label: "VS Code" },
                    { href: "/rsi-prevention/", label: "RSI prevention" },
                  ],
                },
                {
                  title: "Support",
                  links: [
                    { href: "/faq/", label: "FAQ" },
                    { href: "/troubleshooting/", label: "Troubleshooting" },
                    { href: "/alternatives/", label: "Alternatives" },
                    { href: "/privacy/", label: "Privacy" },
                  ],
                },
              ] as { title: string; links: { href: string; label: string }[] }[]
            ).map((col) => (
              <div key={col.title}>
                <h3 className="mb-4 text-sm font-semibold text-zinc-200">
                  {col.title}
                </h3>
                <ul className="space-y-2.5 text-sm">
                  {col.links.map((link) => (
                    <li key={link.href + link.label}>
                      {link.href.startsWith("#") ? (
                        <a
                          href={link.href}
                          className="text-zinc-400 transition-colors hover:text-white"
                        >
                          {link.label}
                        </a>
                      ) : (
                        <Link
                          href={link.href}
                          className="text-zinc-400 transition-colors hover:text-white"
                        >
                          {link.label}
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="flex flex-col items-center justify-between gap-4 border-t border-zinc-800 pt-8 sm:flex-row">
            <p className="text-sm text-zinc-400">
              © {new Date().getFullYear()} Vocalinux. Open-source under AGPL-3.0.
            </p>
            <p className="flex items-center gap-1 text-sm text-zinc-400">
              Made with <Heart className="h-4 w-4 text-primary" /> by{" "}
              <a
                href="https://x.com/intent/user?screen_name=jatinkrmalik"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-white"
              >
                Jatin K Malik
              </a>
            </p>
          </div>
        </div>
      </footer>
    </main>
  );
}
