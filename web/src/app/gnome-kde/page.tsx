import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Keyboard,
  Monitor,
  Settings2,
  Waypoints,
  Wrench,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, AUTHOR_PERSON, buildPageMetadata } from "@/lib/seo";

const comparisonRows = [
  {
    feature: "Default display stack",
    gnome: "Wayland by default on most modern GNOME distributions",
    kde: "Wayland or X11, with X11 still common in some setups",
    icon: Monitor,
  },
  {
    feature: "Text injection approach",
    gnome: "IBus-first for native Wayland dictation",
    kde: "IBus-first on Wayland, with xdotool fallback on X11",
    icon: Keyboard,
  },
  {
    feature: "Input method setup",
    gnome: "Typically straightforward with existing IBus defaults",
    kde: "May need explicit IBus selection in System Settings",
    icon: Settings2,
  },
  {
    feature: "Tray indicator behavior",
    gnome: "Usually needs AppIndicator extension for tray visibility",
    kde: "Native system tray support out of the box",
    icon: Waypoints,
  },
  {
    feature: "Troubleshooting profile",
    gnome: "Extension + IBus engine activation checks",
    kde: "Session type checks (X11 vs Wayland) + input method routing",
    icon: Wrench,
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Voice Typing on GNOME vs KDE Plasma: Linux Desktop Comparison",
  description:
    "Compare voice dictation on GNOME vs KDE Plasma. How desktop environment affects text injection, IBus setup, and Wayland compatibility for Linux voice typing.",
  path: "/gnome-kde",
  keywords: [
    "voice typing GNOME linux",
    "voice dictation KDE plasma",
    "linux desktop voice recognition comparison",
    "GNOME vs KDE voice input",
  ],
});

export default function GnomeVsKdePage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Voice Typing on GNOME vs KDE Plasma: Linux Desktop Comparison",
    description:
      "Compare voice dictation on GNOME vs KDE Plasma. How desktop environment affects text injection, IBus setup, and Wayland compatibility for Linux voice typing.",
    dateModified: "2026-03-30",
    author: AUTHOR_PERSON,
    publisher: {
      "@type": "Organization",
      name: "Vocalinux",
      logo: {
        "@type": "ImageObject",
        url: absoluteUrl("/vocalinux.png"),
      },
    },
    mainEntityOfPage: absoluteUrl("/gnome-kde"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Monitor className="h-4 w-4" />
          Linux Desktop Comparison
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Voice Typing on GNOME vs KDE Plasma: Linux Desktop Comparison
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          GNOME and KDE Plasma both support excellent Linux voice dictation, but the desktop environment
          changes how text injection behaves, how IBus is configured, and what setup steps you need for a
          smooth daily workflow.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">Why desktop environment matters for voice dictation</h2>
        <p className="text-muted-foreground">
          Voice typing quality is not just about the speech engine. Your desktop environment determines
          session type defaults, tray behavior, and input method routing. That affects whether dictation
          appears reliably in every app, especially under Wayland.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">GNOME: what to expect</h2>
        <ul className="space-y-3 text-muted-foreground">
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <strong>Wayland is the default</strong> on modern GNOME sessions, so IBus-backed text
              injection is usually the primary path.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <strong>IBus integration is central</strong> for reliable cross-app dictation behavior on
              Wayland.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <strong>Tray icon often needs AppIndicator support</strong> via GNOME extension, because
              legacy tray behavior differs from KDE.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <strong>Known issues and workarounds:</strong> if the tray icon is missing, install/enable
              AppIndicator extension; if text does not appear in apps, verify IBus daemon/engine state.
            </span>
          </li>
        </ul>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">KDE Plasma: what to expect</h2>
        <ul className="space-y-3 text-muted-foreground">
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <strong>X11 vs Wayland matters</strong>: Plasma supports both widely, so behavior can differ
              between sessions.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <strong>IBus setup may be more explicit</strong> compared with GNOME defaults, depending on
              distro and prior input method configuration.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <strong>System Settings integration is strong</strong>, making it easier to inspect session
              type, input method behavior, and tray settings from one place.
            </span>
          </li>
        </ul>
      </section>

      <section className="mb-12 overflow-x-auto rounded-[12px] border border-border bg-background">
        <h2 className="px-4 pb-2 pt-5 font-display text-2xl font-semibold">GNOME vs KDE Plasma comparison</h2>
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-3 text-sm font-semibold">Feature</th>
              <th className="px-4 py-3 text-sm font-semibold">GNOME</th>
              <th className="px-4 py-3 text-sm font-semibold">KDE Plasma</th>
            </tr>
          </thead>
          <tbody>
            {comparisonRows.map((row) => {
              const Icon = row.icon;
              return (
                <tr key={row.feature} className="border-b border-border align-top">
                  <td className="px-4 py-4 font-semibold">
                    <span className="inline-flex items-center gap-2">
                      <span className="rounded-md bg-primary/10 p-1.5">
                        <Icon className="h-4 w-4 text-primary" />
                      </span>
                      {row.feature}
                    </span>
                  </td>
                  <td className="px-4 py-4 text-sm text-muted-foreground">{row.gnome}</td>
                  <td className="px-4 py-4 text-sm text-muted-foreground">{row.kde}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="mb-12 grid gap-6 md:grid-cols-2">
        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">When GNOME is a better fit</h2>
          <p className="text-sm text-muted-foreground">
            Choose GNOME when you want a Wayland-first environment with familiar IBus defaults and a
            minimal, focused workflow. Add AppIndicator extension once and day-to-day dictation is
            typically very consistent.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">When KDE Plasma is a better fit</h2>
          <p className="text-sm text-muted-foreground">
            Choose KDE Plasma when you want deeper system configurability, flexible X11/Wayland session
            choices, and richer control over desktop behaviors while tuning a dictation setup.
          </p>
        </article>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-muted p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">Helpful guides</h2>
        <div className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-3">
          <Link href="/wayland/" className="font-semibold text-primary hover:underline">
            Wayland setup and architecture
          </Link>
          <Link href="/troubleshooting/" className="font-semibold text-primary hover:underline">
            Troubleshooting checklist
          </Link>
          <Link href="/install/" className="font-semibold text-primary hover:underline">
            Install guide by distro
          </Link>
        </div>
      </section>

      <section className="rounded-[12px] border border-primary/20 bg-primary/5 p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Ready to set up voice typing on your desktop?</h2>
        <p className="mb-6 max-w-3xl text-muted-foreground">
          Install Vocalinux and get reliable offline voice dictation on GNOME or KDE Plasma, with the
          right text injection path for your session type.
        </p>
        <Link
          href="/install/"
          className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
        >
          Install Vocalinux
          <ChevronRight className="h-4 w-4" />
        </Link>
      </section>
    </SeoSubpageShell>
  );
}
