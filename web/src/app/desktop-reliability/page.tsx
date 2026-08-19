import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Keyboard,
  Languages,
  Monitor,
  Power,
  RefreshCw,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const reliabilityFeatures = [
  {
    title: "Suspend and resume recovery",
    description:
      "Vocalinux restarts recognition and shortcut backends after wake so laptop sleep cycles do not require a manual app restart.",
    icon: Power,
  },
  {
    title: "Safe engine switching",
    description:
      "Recognition stops before engine changes, preventing crashes while moving between whisper.cpp, Whisper, VOSK, or Remote API.",
    icon: RefreshCw,
  },
  {
    title: "Keyboard layout preservation",
    description:
      "IBus activation preserves the current XKB layout so dictation does not unexpectedly switch to US keyboard behavior.",
    icon: Keyboard,
  },
  {
    title: "IBus runtime recovery",
    description:
      "Readiness probes, scoped activation, and runtime recovery improve text injection without restarting the whole app.",
    icon: Monitor,
  },
  {
    title: "Non-ASCII fallback",
    description:
      "ydotool can fall back to clipboard paste for accented and non-ASCII characters on paths that cannot type them directly.",
    icon: Languages,
  },
  {
    title: "Tray and settings polish",
    description:
      "Bundled resources, searchable sidebar settings, and an explicit close button improve behavior across desktop environments.",
    icon: Wrench,
  },
];

const releaseMap = [
  {
    version: "v0.16.0",
    highlights:
      "Update checker with tray notifications, Right Alt PTT default for new installs, searchable language list, unused model deletion, Test Dictation missing-model message, IBus/XKB restore fixes, safer audio capture, clipboard restore, installer python3-gi requirement, and AppImage/GPU packaging hardening.",
  },
  {
    version: "v0.15.0",
    highlights:
      "Searchable settings with sidebar dictation footer, ibus-wayland on previously unbridged compositors, safer IBus teardown, Bluetooth mic capture crash fix, custom-shortcut Record/Set restore, and xdotool focus preserve.",
  },
  {
    version: "v0.12.0-beta",
    highlights:
      "Thread safety hardening for Remote API, IBus, and text injection plus better settings behavior.",
  },
  {
    version: "v0.11.0-beta",
    highlights:
      "IBus readiness probes, runtime recovery, final speech preservation, installer hardening, and distro compatibility fixes.",
  },
  {
    version: "v0.10.2-beta",
    highlights:
      "Non-ASCII ydotool fallback, IBus detection on Wayland, startup fixes, and Pop!_OS/Ubuntu dependency coverage.",
  },
  {
    version: "v0.10.1-beta",
    highlights:
      "Suspend/resume recovery, safe engine switching, keyboard layout preservation, tray resources, and push-to-talk reliability.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Linux Desktop Dictation Reliability - IBus, Wayland, Suspend",
  description:
    "See how Vocalinux handles Linux desktop reliability across IBus, Wayland, suspend/resume recovery, keyboard layouts, tray resources, and non-ASCII text injection.",
  path: "/desktop-reliability",
  keywords: [
    "linux dictation reliability",
    "ibus voice dictation wayland",
    "vocalinux suspend resume",
    "wayland text injection reliability",
  ],
});

export default function DesktopReliabilityPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Linux Desktop Dictation Reliability",
    description:
      "Reliability improvements in Vocalinux for IBus, Wayland, suspend/resume, keyboard layout preservation, and text injection.",
    dateModified: "2026-06-11",
    author: {
      "@type": "Person",
      name: "Jatin K Malik",
      url: "https://github.com/jatinkrmalik",
    },
    publisher: {
      "@type": "Organization",
      name: "Vocalinux",
      logo: {
        "@type": "ImageObject",
        url: absoluteUrl("/vocalinux.png"),
      },
    },
    mainEntityOfPage: absoluteUrl("/desktop-reliability"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="border-primary/30 bg-primary/10 mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium text-primary">
          <ShieldCheck className="h-4 w-4" />
          Desktop Reliability
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Reliable Voice Dictation on Real Linux Desktops
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Recent Vocalinux beta releases focused heavily on the hard parts of
          Linux desktop dictation: Wayland text injection, IBus lifecycle
          behavior, suspend/resume recovery, keyboard layouts, non-ASCII text,
          and settings compatibility.
        </p>
      </section>

      <section className="mb-12 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {reliabilityFeatures.map((feature) => {
          const Icon = feature.icon;
          return (
            <article
              key={feature.title}
              className="rounded-[12px] border border-border bg-background p-6"
            >
              <span className="bg-primary/10 mb-4 inline-flex rounded-[12px] p-3">
                <Icon className="h-6 w-6 text-primary" />
              </span>
              <h2 className="mb-2 text-xl font-semibold">{feature.title}</h2>
              <p className="text-sm text-muted-foreground">
                {feature.description}
              </p>
            </article>
          );
        })}
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-muted p-6">
        <h2 className="mb-5 font-display text-2xl font-semibold">Reliability Work by Release</h2>
        <div className="space-y-4">
          {releaseMap.map((release) => (
            <article
              key={release.version}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 text-lg font-semibold">{release.version}</h3>
              <p className="text-sm text-muted-foreground">
                {release.highlights}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-12 grid gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 font-display text-2xl font-semibold">Why This Matters</h2>
          <ul className="space-y-3 text-sm text-muted-foreground">
            {[
              "Dictation should survive laptop lid closes, docking changes, and USB re-enumeration.",
              "Text should appear in the focused app without breaking existing IBus engines or keyboard layouts.",
              "Accented characters should be handled even when a low-level injection backend cannot type them directly.",
              "Settings should fit smaller displays and window managers with different decoration behavior.",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="border-primary/20 bg-primary/5 rounded-[12px] border p-6">
          <h2 className="mb-4 font-display text-2xl font-semibold">Where to Debug Issues</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            If dictation works in one app but not another, start with the
            display server and input method path. Wayland sessions often depend
            on IBus setup, while X11 paths typically use xdotool or compatible
            fallbacks.
          </p>
          <Link
            href="/troubleshooting/"
            className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline"
          >
            Open troubleshooting guide <ChevronRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      <section className="border-primary/20 bg-primary/5 rounded-[12px] border p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Related Guides</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Link href="/wayland/" className="group">
            <h3 className="font-semibold">Wayland support</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Understand IBus, wtype, ydotool, and compositor-specific setup.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Wayland guide <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/shortcuts/" className="group">
            <h3 className="font-semibold">Shortcut reliability</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Configure toggle, push-to-talk, and left/right modifier behavior.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Shortcut guide <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/changelog/" className="group">
            <h3 className="font-semibold">Release history</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Review each beta release and the reliability fixes it included.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Changelog <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
