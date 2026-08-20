import Link from "next/link";
import { type Metadata } from "next";
import { notFound } from "next/navigation";
import {
  CheckCircle2,
  ChevronRight,
  Cpu,
  Laptop,
  Shield,
  Sparkles,
  Terminal,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

type DistroSlug = "ubuntu" | "fedora" | "arch";
type DistroParams = { distro: string } | Promise<{ distro: string }>;

interface DistroConfig {
  name: string;
  title: string;
  description: string;
  intro: string;
  prerequisites: string[];
  testedOn: string[];
  installCommand: string;
  setupNotes: string[];
  postInstallChecks: string[];
}

const distroConfig: Record<DistroSlug, DistroConfig> = {
  ubuntu: {
    name: "Ubuntu",
    title: "Install Voice Dictation on Ubuntu",
    description:
      "Step-by-step Ubuntu voice dictation setup for offline speech-to-text with whisper.cpp and VOSK. Works on Ubuntu 22.04+, GNOME, KDE, X11, and Wayland.",
    intro:
      "This Ubuntu guide is tuned for practical desktop use: terminals, browsers, IDEs, office suites, and chat apps. Local engines keep audio on your machine. Remote API is optional.",
    prerequisites: [
       "Ubuntu 22.04+ (or Ubuntu-based distro)",
       "Python 3.9+",
      "Working microphone",
      "curl installed (sudo apt update && sudo apt install -y curl)",
    ],
    testedOn: [
      "Ubuntu 24.04 LTS (GNOME, Wayland)",
      "Ubuntu 22.04 LTS (GNOME, X11)",
      "Kubuntu and Linux Mint derivatives",
    ],
    installCommand:
      "curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh && bash /tmp/vl.sh --interactive",
    setupNotes: [
      "Choose whisper.cpp for the fastest setup and cross-vendor GPU support.",
      "On lower-RAM systems, pick VOSK for lightweight realtime dictation.",
      "If your desktop uses Wayland, keep keyboard injection defaults unless you know your compositor specifics.",
    ],
    postInstallChecks: [
      "Run vocalinux and confirm the tray indicator appears.",
      "Hold Right Alt (Option) to dictate, or switch to toggle mode in Settings and verify dictation starts.",
      "Set language and model size in the settings panel for your workload.",
    ],
  },
  fedora: {
    name: "Fedora",
    title: "Install Voice Dictation on Fedora",
    description:
      "Fedora speech-to-text installation guide for Vocalinux. Set up offline Linux voice typing on Fedora Workstation with Wayland or X11.",
    intro:
      "Fedora is an excellent match for Vocalinux thanks to current Python stacks and up-to-date system libraries. This guide focuses on reliable setup and minimal friction.",
    prerequisites: [
       "Fedora Workstation 39+ (or Fedora-based distro)",
       "Python 3.9+",
      "Working microphone",
      "curl installed (sudo dnf install -y curl)",
    ],
    testedOn: [
      "Fedora Workstation 41 (Wayland)",
      "Fedora Workstation 40 (X11 fallback)",
      "Fedora KDE spin",
    ],
    installCommand:
      "curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh && bash /tmp/vl.sh --interactive",
    setupNotes: [
      "If prompted for optional dependencies, accept defaults unless your desktop setup requires custom input tooling.",
      "Keep the default whisper.cpp engine for best speed-to-accuracy tradeoff.",
      "Use the smallest model first, then scale up after confirming stable dictation latency.",
    ],
    postInstallChecks: [
      "Run vocalinux from terminal and test transcription in GNOME Text Editor or VS Code.",
      "Verify toggle mode and push-to-talk behavior with your preferred keyboard layout.",
      "Confirm startup behavior and language settings persist after reboot.",
    ],
  },
  arch: {
    name: "Arch Linux",
    title: "Install Voice Dictation on Arch Linux",
    description:
      "Arch Linux voice dictation guide for offline speech recognition. Install Vocalinux on Arch, Manjaro, and EndeavourOS with distro-aware setup notes.",
    intro:
      "Arch users usually care about control and performance. This guide keeps setup lean while preserving compatibility across rolling-release desktop environments.",
    prerequisites: [
       "Arch Linux / Manjaro / EndeavourOS",
       "Python 3.9+",
      "Working microphone",
      "curl installed (sudo pacman -Sy --needed curl)",
    ],
    testedOn: [
      "Arch Linux (GNOME, Wayland)",
      "Arch Linux (KDE Plasma)",
      "Manjaro (X11 and Wayland sessions)",
    ],
    installCommand:
      "curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh && bash /tmp/vl.sh --interactive",
    setupNotes: [
      "Prefer whisper.cpp for lower dependency footprint and faster cold start.",
      "On custom compositor setups, verify text injection behavior in both terminal and browser contexts.",
      "If you tweak keybinds heavily, set a non-conflicting activation shortcut in Vocalinux settings.",
    ],
    postInstallChecks: [
      "Run vocalinux and test dictation in multiple apps (terminal, browser, editor).",
      "Confirm your chosen speech engine model balances latency and accuracy.",
      "Back up ~/.config/vocalinux/config.json after tuning preferences.",
    ],
  },
};

const distroKeywords: Record<DistroSlug, string[]> = {
  ubuntu: [
    "ubuntu voice dictation",
    "speech to text ubuntu",
    "ubuntu voice typing",
    "offline dictation ubuntu",
  ],
  fedora: [
    "fedora voice dictation",
    "speech to text fedora",
    "fedora voice typing",
    "offline dictation fedora",
  ],
  arch: [
    "arch linux voice dictation",
    "speech to text arch linux",
    "manjaro dictation",
    "offline dictation arch",
  ],
};

const isDistroSlug = (value: string): value is DistroSlug => {
  return value in distroConfig;
};

const resolveParams = async (params: DistroParams): Promise<{ distro: string }> => {
  return Promise.resolve(params);
};

const getDistroStyles = (distro: DistroSlug) => {
  if (distro === "ubuntu") {
    return {
      icon: Laptop,
      iconClass: "text-primary",
      chipClass: "border-border bg-muted text-muted-foreground",
      panelClass: "bg-primary/10",
    };
  }

  if (distro === "fedora") {
    return {
      icon: Sparkles,
      iconClass: "text-primary",
      chipClass: "border-border bg-primary/10 text-primary",
      panelClass: "bg-primary/10",
    };
  }

  return {
    icon: Cpu,
    iconClass: "text-primary",
    chipClass: "border-border bg-primary/10 text-muted-foreground",
    panelClass: "bg-primary/10",
  };
};

export function generateStaticParams() {
  return Object.keys(distroConfig).map((distro) => ({ distro }));
}

export async function generateMetadata({
  params,
}: {
  params: DistroParams;
}): Promise<Metadata> {
  const { distro } = await resolveParams(params);

  if (!isDistroSlug(distro)) {
    return buildPageMetadata({
      title: "Linux Voice Dictation Install Guide",
      description:
        "Install Vocalinux on Linux with distro-specific setup instructions for Ubuntu, Fedora, and Arch.",
      path: "/install",
    });
  }

  const config = distroConfig[distro];

  return buildPageMetadata({
    title: config.title,
    description: config.description,
    path: `/install/${distro}`,
    keywords: distroKeywords[distro],
  });
}

export default async function DistroInstallPage({
  params,
}: {
  params: DistroParams;
}) {
  const { distro } = await resolveParams(params);

  if (!isDistroSlug(distro)) {
    notFound();
  }

  const config = distroConfig[distro];
  const styles = getDistroStyles(distro);
  const DistroIcon = styles.icon;

  const howToJsonLd = {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: `${config.title} in 3 Steps`,
    description: config.description,
    inLanguage: "en-US",
    totalTime: "PT10M",
    supply: [
      {
        "@type": "HowToSupply",
        name: "Linux computer",
      },
      {
        "@type": "HowToSupply",
        name: "Microphone",
      },
    ],
    tool: [
      {
        "@type": "HowToTool",
        name: "Terminal",
      },
    ],
    step: [
      {
        "@type": "HowToStep",
        name: "Open terminal",
        text: "Launch your terminal application and ensure curl is available.",
        url: absoluteUrl(`/install/${distro}`),
      },
      {
        "@type": "HowToStep",
        name: "Run installer",
        text: `Run: ${config.installCommand}`,
        url: absoluteUrl(`/install/${distro}`),
      },
      {
        "@type": "HowToStep",
        name: "Start dictating",
        text: "Launch vocalinux and hold Right Alt (Option) to begin dictation, or choose toggle mode in Settings.",
        url: absoluteUrl(`/install/${distro}`),
      },
    ],
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(howToJsonLd) }}
      />

      <nav className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/" className="hover:text-foreground hover:underline">
          Home
        </Link>
        <ChevronRight className="h-4 w-4" />
        <Link href="/install/" className="hover:text-foreground hover:underline">
          Install Guides
        </Link>
        <ChevronRight className="h-4 w-4" />
        <span className="font-medium text-foreground">{config.name}</span>
      </nav>

      <section>
        <p
          className={`mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium ${styles.chipClass}`}
        >
          <DistroIcon className={`h-4 w-4 ${styles.iconClass}`} />
          {config.name} Setup Guide
        </p>

        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">{config.title}</h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">{config.intro}</p>

        <div
          className={`rounded-[12px] border border-border p-6  ${styles.panelClass}`}
        >
          <h2 className="mb-3 inline-flex items-center gap-2 text-xl font-semibold">
            <Terminal className="h-5 w-5 text-primary dark:text-[color:var(--terminal-fg)]" />
            Install command
          </h2>
          <div className="rounded-[12px] bg-[color:var(--terminal)] p-4">
            <code className="block overflow-x-auto whitespace-pre-wrap break-all text-sm text-[color:var(--terminal-fg)] sm:text-base">
              {config.installCommand}
            </code>
          </div>
        </div>
      </section>

      <section className="mt-10 grid gap-6 md:grid-cols-2">
        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 inline-flex items-center gap-2 text-2xl font-semibold">
            <Shield className="h-5 w-5 text-primary" />
            Prerequisites
          </h2>
          <ul className="space-y-2 text-muted-foreground">
            {config.prerequisites.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                {item}
              </li>
            ))}
          </ul>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 inline-flex items-center gap-2 text-2xl font-semibold">
            <Sparkles className="h-5 w-5 text-primary" />
            Tested environments
          </h2>
          <ul className="space-y-2 text-muted-foreground">
            {config.testedOn.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                {item}
              </li>
            ))}
          </ul>
        </article>
      </section>

      <section className="mt-10 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 inline-flex items-center gap-2 text-2xl font-semibold">
          <Cpu className="h-5 w-5 text-primary" />
          Setup notes for {config.name}
        </h2>
        <ol className="space-y-3 text-muted-foreground">
          {config.setupNotes.map((item) => (
            <li key={item} className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
              {item}
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-10 rounded-[12px] border border-border bg-muted p-6 /70">
        <h2 className="mb-4 inline-flex items-center gap-2 text-2xl font-semibold">
          <CheckCircle2 className="h-5 w-5 text-primary" />
          Post-install checklist
        </h2>
        <ul className="space-y-3 text-muted-foreground">
          {config.postInstallChecks.map((item) => (
            <li key={item} className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
              {item}
            </li>
          ))}
        </ul>

        <p className="mt-6 text-sm text-muted-foreground">
          Need help selecting an engine? Read the
          <Link href="/compare/" className="ml-1 font-semibold text-primary hover:underline">
            whisper.cpp vs Whisper vs VOSK comparison
          </Link>
          .
        </p>
      </section>
    </SeoSubpageShell>
  );
}
