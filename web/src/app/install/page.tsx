import Link from "next/link";
import { type Metadata } from "next";
import { ChevronRight, Cpu, Laptop, Terminal } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { buildPageMetadata } from "@/lib/seo";

const installCommand =
  "curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh && bash /tmp/vl.sh --interactive";

const distroGuides = [
  {
    name: "Ubuntu",
    href: "/install/ubuntu/",
    description:
      "Install offline voice dictation on Ubuntu 22.04+ with GNOME, KDE, X11, or Wayland.",
    icon: Laptop,
  },
  {
    name: "Fedora",
    href: "/install/fedora/",
    description:
      "Set up speech-to-text on Fedora Workstation and Silverblue with distro-specific notes.",
    icon: Terminal,
  },
  {
    name: "Arch Linux",
    href: "/install/arch/",
    description:
      "Install Vocalinux on Arch, Manjaro, and EndeavourOS with package prerequisites and tips.",
    icon: Cpu,
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Install Voice Dictation on Linux (Ubuntu, Fedora, Arch)",
  description:
    "Step-by-step Linux voice dictation installation guides for Ubuntu, Fedora, and Arch. Install Vocalinux in minutes and start offline speech-to-text.",
  path: "/install",
  keywords: [
    "install voice dictation linux",
    "linux speech to text setup",
    "ubuntu voice typing install",
    "fedora speech recognition",
    "arch linux dictation",
  ],
});

export default function InstallGuidesPage() {
  return (
    <SeoSubpageShell>
      <section>
        <p className="subpage-kicker">Linux installation</p>
        <h1>Install Voice Dictation on Linux</h1>
        <p className="subpage-lede">
          Pick your distro guide and follow a proven setup flow for offline
          speech-to-text on Linux. Every guide is written for real desktop usage.
        </p>

        <div className="subpage-terminal mt-8 p-5 sm:p-6">
          <p className="mb-3 inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            <Terminal className="h-3.5 w-3.5 text-[color:var(--terminal-fg)]" />
            install.sh --interactive
          </p>
          <code className="block overflow-x-auto break-all text-sm sm:text-base">
            {installCommand}
          </code>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Prefer no installer? Download an{" "}
          <a
            href="https://github.com/VocaHQ/vocalinux/releases"
            className="font-semibold text-primary hover:underline"
          >
            AppImage
          </a>{" "}
          for x86_64 or aarch64 from GitHub Releases (host text-injection tools
          still required).
        </p>
      </section>

      <section className="mt-12 grid gap-4 md:grid-cols-3">
        {distroGuides.map((guide) => {
          const Icon = guide.icon;
          return (
            <Link
              key={guide.href}
              href={guide.href}
              className="subpage-card group p-5"
            >
              <div className="mb-3 inline-flex rounded-[10px] bg-primary/10 p-2.5">
                <Icon className="h-5 w-5 text-primary" />
              </div>
              <h2 className="mb-2 text-xl font-semibold">{guide.name}</h2>
              <p className="mb-4 text-sm text-muted-foreground">
                {guide.description}
              </p>
              <span className="inline-flex items-center gap-1 text-sm font-semibold text-primary">
                Read {guide.name} guide
                <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          );
        })}
      </section>

      <section className="subpage-panel mt-12 p-6 sm:p-8">
        <h2 className="mb-4">After installation</h2>
        <ul className="space-y-3 text-muted-foreground">
          <li>
            Launch with{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm text-foreground">
              vocalinux
            </code>
            .
          </li>
          <li>
            Hold Right Alt (Option) to dictate, or switch to toggle mode in Settings.
          </li>
          <li>
            Choose whisper.cpp for speed, Whisper for maximum model
            compatibility, or VOSK for low-RAM systems.
          </li>
        </ul>
        <p className="mt-6 text-sm text-muted-foreground">
          Need help choosing an engine? See the{" "}
          <Link
            href="/compare/"
            className="font-semibold text-primary hover:underline"
          >
            speech engine comparison
          </Link>
          .
        </p>
      </section>
    </SeoSubpageShell>
  );
}
