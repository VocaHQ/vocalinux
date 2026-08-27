import Link from "next/link";
import { type Metadata } from "next";
import { CheckCircle2, ChevronRight, Loader2, Play, Power, Settings, Terminal } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const desktopEnvironments = [
  {
    name: "GNOME",
    autostartMethod: "XDG Autostart",
    supported: true,
    notes: "Default on Ubuntu, Fedora, Debian",
  },
  {
    name: "KDE Plasma",
    autostartMethod: "XDG Autostart",
    supported: true,
    notes: "Full support via System Settings",
  },
  {
    name: "Xfce",
    autostartMethod: "XDG Autostart",
    supported: true,
    notes: "Settings → Session and Startup",
  },
  {
    name: "Cinnamon",
    autostartMethod: "XDG Autostart",
    supported: true,
    notes: "System Settings → Startup Applications",
  },
  {
    name: "MATE",
    autostartMethod: "XDG Autostart",
    supported: true,
    notes: "Control Center → Startup Applications",
  },
  {
    name: "LXQt",
    autostartMethod: "XDG Autostart",
    supported: true,
    notes: "Preferences → LXQt Settings → Autostart",
  },
  {
    name: "Sway",
    autostartMethod: "XDG Autostart / config",
    supported: true,
    notes: "Use dex or exec in config",
  },
  {
    name: "Hyprland",
    autostartMethod: "XDG Autostart / config",
    supported: true,
    notes: "exec-once in config or XDG",
  },
];

const howItWorks = [
  {
    step: 1,
    title: "Enable in Vocalinux",
    description: "Open Vocalinux and enable 'Start on Login' via the tray menu or Settings dialog.",
    code: null,
  },
  {
    step: 2,
    title: "Desktop Entry Created",
    description: "Vocalinux creates a .desktop file in your autostart directory:",
    code: "~/.config/autostart/vocalinux.desktop",
  },
  {
    step: 3,
    title: "Auto-launch on Login",
    description: "Your desktop environment reads this file and launches Vocalinux when you log in.",
    code: null,
  },
];

const managementMethods = [
  {
    method: "System Tray",
    description: "Right-click the Vocalinux tray icon → Start on Login",
    icon: Power,
  },
  {
    method: "Settings Dialog",
    description: "Open Settings → General → Start on Login",
    icon: Settings,
  },
  {
    method: "Command Line",
    description: "Create/remove the autostart file manually",
    icon: Terminal,
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Autostart Voice Dictation on Linux Login | Vocalinux",
  description:
    "Configure Vocalinux to start automatically when you log in to Linux. XDG autostart support for GNOME, KDE, Xfce, and all major desktop environments.",
  path: "/autostart",
  keywords: [
    "Linux autostart voice dictation",
    "auto start on login Linux",
    "XDG autostart desktop entry",
    "GNOME startup applications",
    "KDE autostart",
    "voice dictation auto launch",
    "Linux desktop autostart",
  ],
});

export default function AutostartPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Autostart Voice Dictation on Linux Login",
    description:
      "How to configure Vocalinux to start automatically on Linux login. XDG autostart guide for all desktop environments.",
    dateModified: "2026-02-22",
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
    mainEntityOfPage: absoluteUrl("/autostart"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Power className="h-4 w-4" />
          New in v0.7.0
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Autostart Voice Dictation on Login
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Have Vocalinux ready to go the moment you log in. Uses the Linux-standard XDG autostart
          mechanism - works with GNOME, KDE, Xfce, and all major desktop environments.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-3">
        {managementMethods.map((method) => {
          const Icon = method.icon;
          return (
            <div
              key={method.method}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <Icon className="mb-3 h-6 w-6 text-primary" />
              <h3 className="mb-2 font-semibold">{method.method}</h3>
              <p className="text-sm text-muted-foreground">{method.description}</p>
            </div>
          );
        })}
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">How It Works</h2>
        <div className="space-y-4">
          {howItWorks.map((step) => (
            <div
              key={step.step}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <div className="mb-2 flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {step.step}
                </span>
                <h3 className="font-semibold">{step.title}</h3>
              </div>
              <p className="ml-10 text-sm text-muted-foreground">{step.description}</p>
              {step.code && (
                <div className="ml-10 mt-2 rounded-lg bg-[color:var(--terminal)] p-2">
                  <code className="text-sm text-[color:var(--terminal-fg)]">{step.code}</code>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-6 font-display text-2xl font-semibold">Desktop Environment Compatibility</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Vocalinux uses the XDG Autostart specification, which is supported by virtually all Linux
          desktop environments:
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Desktop</th>
                <th className="pb-3 pr-4 font-semibold">Method</th>
                <th className="pb-3 pr-4 font-semibold">Supported</th>
                <th className="pb-3 font-semibold">Notes</th>
              </tr>
            </thead>
            <tbody>
              {desktopEnvironments.map((de) => (
                <tr key={de.name} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{de.name}</td>
                  <td className="py-3 pr-4 text-muted-foreground">{de.autostartMethod}</td>
                  <td className="py-3 pr-4">
                    {de.supported ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        <CheckCircle2 className="h-3 w-3" />
                        Yes
                      </span>
                    ) : (
                      <span className="text-muted-foreground"> - </span>
                    )}
                  </td>
                  <td className="py-3 text-muted-foreground">{de.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-primary/5 p-6">
        <h2 className="mb-3 text-xl font-semibold text-foreground">
          Not a systemd Service
        </h2>
        <p className="text-sm text-muted-foreground">
          Vocalinux autostart uses <strong>XDG desktop entries</strong>, not systemd services. This
          means it starts as a regular desktop application in your graphical session - which is the
          correct way to launch GUI apps. No background services, no root required.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">Manual Setup (Advanced)</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          If you prefer to manage autostart manually or need to customize the startup behavior:
        </p>
        <div className="space-y-3">
          <div>
            <p className="mb-1 text-sm font-medium">Enable autostart:</p>
            <div className="rounded-lg bg-[color:var(--terminal)] p-3">
              <code className="text-sm text-[color:var(--terminal-fg)]">
                mkdir -p ~/.config/autostart && cp /usr/share/applications/vocalinux.desktop
                ~/.config/autostart/
              </code>
            </div>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium">Disable autostart:</p>
            <div className="rounded-lg bg-[color:var(--terminal)] p-3">
              <code className="text-sm text-[color:var(--terminal-fg)]">rm ~/.config/autostart/vocalinux.desktop</code>
            </div>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium">Start minimized (skip welcome dialog):</p>
            <div className="rounded-lg bg-[color:var(--terminal)] p-3">
              <code className="text-sm text-[color:var(--terminal-fg)]">
                vocalinux --start-minimized
              </code>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Ready to Automate?</h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux and enable autostart. Your voice dictation will be ready the moment you
          log in.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/install/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Install Now
            <ChevronRight className="h-4 w-4" />
          </Link>
          <Link
            href="/faq/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted hover:bg-muted"
          >
            Common Questions
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
