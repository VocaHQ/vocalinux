import Link from "next/link";
import { type Metadata } from "next";
import { notFound } from "next/navigation";
import {
  CheckCircle2,
  ChevronRight,
  Cpu,
  Download,
  Laptop,
  Monitor,
  RefreshCw,
  Server,
  Shield,
  Sparkles,
  Terminal,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

type DistroSlug =
  | "ubuntu"
  | "debian"
  | "fedora"
  | "arch"
  | "opensuse"
  | "linux-mint"
  | "pop-os";
type DistroParams = { distro: string } | Promise<{ distro: string }>;

interface InstallOption {
  label: string;
  note: string;
  command: string;
}

interface DistroConfig {
  name: string;
  title: string;
  description: string;
  intro: string;
  prerequisites: string[];
  supportedOn: string[];
  installCommand: string;
  otherInstallOptions: InstallOption[];
  setupNotes: string[];
  postInstallChecks: string[];
}

const INSTALL_SCRIPT_COMMAND = `curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh
bash /tmp/vl.sh`;

const DEB_OPTION: InstallOption = {
  label: "Native .deb package",
  note: "Download the .deb for your CPU from GitHub Releases (arm64 files are attached too). It is a thin package: Python and GTK come from the distro, whisper.cpp runs on the CPU, and there is no auto-update. On Wayland, add yourself to the input group (sudo usermod -aG input $USER, then log out and back in) or the default hotkey stays off.",
  command: "sudo apt install ./vocalinux_*_amd64.deb",
};

const RPM_OPTION: InstallOption = {
  label: "Native .rpm package",
  note: "Download the .rpm for your CPU from GitHub Releases (aarch64 files are attached too). It is a thin package: Python and GTK come from Fedora, whisper.cpp runs on the CPU, and there is no auto-update or COPR yet. On Wayland, add yourself to the input group (sudo usermod -aG input $USER, then log out and back in) or the default hotkey stays off.",
  command: "sudo dnf install ./vocalinux-*.x86_64.rpm",
};

const FLATPAK_OPTION: InstallOption = {
  label: "Flatpak from the VocaHQ remote",
  note: "Not on Flathub. The self-hosted vocahq remote updates with flatpak update and ships whisper.cpp only.",
  command:
    "flatpak install https://vocahq.github.io/vocalinux-flatpak/com.vocalinux.Vocalinux.flatpakref",
};

const COMMON_CHECKS = [
  "Run vocalinux --version to confirm the installed release.",
  "Launch vocalinux and confirm the tray icon appears. On GNOME, the tray needs the AppIndicator extension.",
  "Hold Right Alt (Option) to dictate, or switch to toggle mode in Settings → Shortcuts, and confirm text lands in a terminal and a browser.",
  "If anything misbehaves, run vocalinux --debug and check the troubleshooting guide.",
];

const distroConfig: Record<DistroSlug, DistroConfig> = {
  ubuntu: {
    name: "Ubuntu",
    title: "Install Voice Dictation on Ubuntu",
    description:
      "Step-by-step Ubuntu voice dictation setup for offline speech-to-text with whisper.cpp. Covers Ubuntu 24.04+, the install script, the .deb, X11 and Wayland.",
    intro:
      "This Ubuntu guide is tuned for practical desktop use: terminals, browsers, IDEs, office suites, and chat apps. Local engines keep audio on your machine after the one-time model download. Remote API is optional.",
    prerequisites: [
      "Ubuntu 24.04 or newer (Ubuntu 22.04 ships Python 3.10, below the 3.11 floor)",
      "Python 3.11+ with the distro's python3-gi (the installer handles this)",
      "Working microphone",
      "curl installed (sudo apt update && sudo apt install -y curl)",
    ],
    supportedOn: [
      "Ubuntu 24.04 LTS and newer: full support",
      "Ubuntu-based derivatives on a 24.04 base, such as Linux Mint 22, Pop!_OS 24.04, elementary OS 8 and Zorin OS on 24.04",
    ],
    installCommand: INSTALL_SCRIPT_COMMAND,
    otherInstallOptions: [DEB_OPTION, FLATPAK_OPTION],
    setupNotes: [
      "Keep the default whisper.cpp engine: it installs in about 1-2 minutes and uses a Vulkan GPU when one is available.",
      "On lower-RAM systems, VOSK is the lightweight option (--engine=vosk with the install script).",
      "On KDE Plasma Wayland (Kubuntu), set System Settings → Keyboard → Virtual Keyboard to IBus Wayland.",
      "The install script adds you to the input group for Wayland hotkeys; log out and back in afterwards.",
    ],
    postInstallChecks: [
      ...COMMON_CHECKS,
      "Set language and model size in Settings → Speech Model for your workload.",
    ],
  },
  debian: {
    name: "Debian",
    title: "Install Voice Dictation on Debian",
    description:
      "Install Vocalinux offline voice dictation on Debian 12, 13 and Testing with the install script or the native .deb. Covers AppIndicator, ydotool and Wayland.",
    intro:
      "Debian 12 and newer are a primary target for Vocalinux. The install script detects Debian, installs the system packages it needs, and sets up whisper.cpp with a checksum-verified tiny model.",
    prerequisites: [
      "Debian 12 or newer, including Testing (Debian 11 and earlier are below the Python 3.11 floor)",
      "Python 3.11+ with the distro's python3-gi (the installer handles this)",
      "Working microphone",
      "curl installed (sudo apt update && sudo apt install -y curl)",
    ],
    supportedOn: [
      "Debian 12 and newer: full support",
      "Debian Testing: full support",
    ],
    installCommand: INSTALL_SCRIPT_COMMAND,
    otherInstallOptions: [DEB_OPTION, FLATPAK_OPTION],
    setupNotes: [
      "Debian uses the Ayatana AppIndicator for the tray (gir1.2-ayatanaappindicator3-0.1); the installer picks it.",
      "Clean Debian installs lack some build tools for compiling pywhispercpp (libssl-dev, autoconf, automake, libtool, patchelf). The installer adds them; add them yourself before a manual rebuild.",
      "ydotool is not in Debian's standard repositories. Vocalinux falls back to IBus or wtype for most Wayland compositors.",
      "On KDE Plasma Wayland, set System Settings → Keyboard → Virtual Keyboard to IBus Wayland.",
    ],
    postInstallChecks: [
      ...COMMON_CHECKS,
      "On GNOME, install gnome-shell-extension-appindicator if the tray icon never appears.",
    ],
  },
  fedora: {
    name: "Fedora",
    title: "Install Voice Dictation on Fedora",
    description:
      "Fedora speech-to-text installation guide for Vocalinux. Set up offline Linux voice typing on Fedora 42+ with the install script or .rpm, on Wayland or X11.",
    intro:
      "Fedora 42 and newer ship the Python and GTK stack Vocalinux needs, and Fedora 42 is the release in the project's CI matrix. This guide focuses on reliable setup and minimal friction.",
    prerequisites: [
      "Fedora 42 or newer (Workstation or a spin)",
      "Python 3.11+ with python3-gobject (the installer handles this)",
      "Working microphone",
      "curl installed (sudo dnf install -y curl)",
    ],
    supportedOn: ["Fedora 42 and newer: good support (uses lib64 paths)"],
    installCommand: INSTALL_SCRIPT_COMMAND,
    otherInstallOptions: [RPM_OPTION, FLATPAK_OPTION],
    setupNotes: [
      "If prompted for optional dependencies, accept defaults unless your desktop setup requires custom input tooling.",
      "Keep the default whisper.cpp engine for the best speed-to-accuracy tradeoff.",
      "Use the smallest model first, then scale up once dictation feels stable on your hardware.",
      "On the KDE spin under Wayland, set System Settings → Keyboard → Virtual Keyboard to IBus Wayland.",
    ],
    postInstallChecks: [
      ...COMMON_CHECKS,
      "Confirm startup behavior and language settings persist after reboot.",
    ],
  },
  arch: {
    name: "Arch Linux",
    title: "Install Voice Dictation on Arch Linux",
    description:
      "Arch Linux voice dictation guide for offline speech recognition. Install Vocalinux from the AUR or the install script on Arch, Manjaro and EndeavourOS.",
    intro:
      "Arch users can install Vocalinux from the AUR or with the install script. Both keep whisper.cpp as the default engine and work across rolling-release desktops.",
    prerequisites: [
      "Arch Linux, Manjaro or EndeavourOS",
      "Python 3.11+ with python-gobject",
      "Working microphone",
      "curl installed (sudo pacman -Sy --needed curl), or an AUR helper such as yay",
    ],
    supportedOn: [
      "Arch Linux (rolling): good support",
      "Manjaro (rolling): good support, inherits Arch compatibility",
      "EndeavourOS (rolling): good support, inherits Arch compatibility",
    ],
    installCommand: INSTALL_SCRIPT_COMMAND,
    otherInstallOptions: [
      {
        label: "AUR packages",
        note: "vocalinux builds the canonical release sdist against Arch dependencies. vocalinux-bin installs the prebuilt release AppImage. vocalinux-git is a community package that tracks main. The three conflict, so install only one.",
        command: `yay -S vocalinux          # canonical release sdist, built against Arch dependencies
yay -S vocalinux-git      # community package; tracks main`,
      },
    ],
    setupNotes: [
      "Prefer whisper.cpp: it avoids the full PyTorch stack that OpenAI Whisper pulls in.",
      "On custom compositor setups, verify text injection behavior in both terminal and browser contexts.",
      "If you tweak keybinds heavily, set a non-conflicting activation shortcut in Vocalinux settings.",
      "AUR packages update with your AUR helper; the in-app update checker only notifies.",
    ],
    postInstallChecks: [
      ...COMMON_CHECKS,
      "Back up ~/.config/vocalinux/config.json after tuning preferences.",
    ],
  },
  opensuse: {
    name: "openSUSE",
    title: "Install Voice Dictation on openSUSE",
    description:
      "Install Vocalinux offline voice dictation on openSUSE Tumbleweed with the install script. Covers versioned Python packages, Vulkan builds, X11 and Wayland.",
    intro:
      "On openSUSE Tumbleweed the install script uses zypper, resolves the versioned Python packages for your snapshot, and sets up whisper.cpp with a checksum-verified tiny model.",
    prerequisites: [
      "openSUSE Tumbleweed",
      "Python 3.11+ with the matching pythonXY-gobject package (the installer handles this)",
      "Working microphone",
      "curl installed (sudo zypper install curl)",
    ],
    supportedOn: [
      "openSUSE Tumbleweed: good support",
      "openSUSE Leap is not listed in the compatibility matrix",
    ],
    installCommand: INSTALL_SCRIPT_COMMAND,
    otherInstallOptions: [
      FLATPAK_OPTION,
      {
        label: "AppImage",
        note: "Download the x86_64 or aarch64 AppImage from GitHub Releases. It starts on Tumbleweed and uses Vulkan through the host driver, but still needs host text-injection tools (xdotool on X11; wtype, ydotool or clipboard tools on Wayland).",
        command: `chmod +x Vocalinux-*-x86_64.AppImage   # or aarch64
./Vocalinux-*-x86_64.AppImage`,
      },
    ],
    setupNotes: [
      "Tumbleweed uses versioned Python package names such as python313-devel. The -devel suffix means development headers, not beta packages.",
      "For a manual install, if ${PYVER}-virtualenv is unavailable on your snapshot, try ${PYVER}-venv.",
      "For whisper.cpp Vulkan GPU builds, install vulkan-tools, vulkan-devel and shaderc (sudo zypper install -y vulkan-tools vulkan-devel shaderc).",
      "On KDE Plasma Wayland, set System Settings → Keyboard → Virtual Keyboard to IBus Wayland.",
    ],
    postInstallChecks: [
      ...COMMON_CHECKS,
      "Run vulkaninfo --summary if you expect GPU acceleration.",
    ],
  },
  "linux-mint": {
    name: "Linux Mint",
    title: "Install Voice Dictation on Linux Mint",
    description:
      "Install Vocalinux offline voice dictation on Linux Mint 22 with the install script or .deb. Covers Cinnamon, the Ubuntu 24.04 base and why Mint 21 is too old.",
    intro:
      "Linux Mint is judged by its Ubuntu base, not its own version number. Mint 22 is built on Ubuntu 24.04, so the install script treats it as Ubuntu and installs everything Vocalinux needs.",
    prerequisites: [
      "Linux Mint 22 or newer, on an Ubuntu 24.04+ base (Mint 21 is on Ubuntu 22.04, below the floor)",
      "Python 3.11+ with the distro's python3-gi (the installer handles this)",
      "Working microphone",
      "curl installed (sudo apt update && sudo apt install -y curl)",
    ],
    supportedOn: [
      "Linux Mint on Ubuntu 24.04+ (Mint 22): good support",
      "Cinnamon, MATE and Xfce desktops: full support",
    ],
    installCommand: INSTALL_SCRIPT_COMMAND,
    otherInstallOptions: [
      {
        ...DEB_OPTION,
        note: `The .deb targets Debian 12+ and Ubuntu 24.04+, the base Mint 22 is built on. ${DEB_OPTION.note}`,
      },
      FLATPAK_OPTION,
    ],
    setupNotes: [
      "Keep the default whisper.cpp engine unless you have a specific reason to switch.",
      "Cinnamon is fully supported and works with AppIndicator for the tray icon.",
      "Text is typed with xdotool on X11 sessions; on Wayland, Vocalinux picks from IBus, the RemoteDesktop portal, wtype or ydotool.",
      "The install script adds you to the input group for Wayland hotkeys; log out and back in afterwards.",
    ],
    postInstallChecks: [...COMMON_CHECKS],
  },
  "pop-os": {
    name: "Pop!_OS",
    title: "Install Voice Dictation on Pop!_OS",
    description:
      "Install Vocalinux offline voice dictation on Pop!_OS 24.04 with the install script or .deb. Covers the Ubuntu base, Wayland hotkeys and fallback options.",
    intro:
      "Pop!_OS uses Ubuntu's own version numbering, and 24.04 and newer meet the Python 3.11 floor. The install script detects Pop!_OS as part of the Ubuntu family.",
    prerequisites: [
      "Pop!_OS 24.04 or newer",
      "Python 3.11+ with the distro's python3-gi (the installer handles this)",
      "Working microphone",
      "curl installed (sudo apt update && sudo apt install -y curl)",
    ],
    supportedOn: ["Pop!_OS 24.04 and newer: good support"],
    installCommand: INSTALL_SCRIPT_COMMAND,
    otherInstallOptions: [DEB_OPTION, FLATPAK_OPTION],
    setupNotes: [
      "For a manual install, use libgirepository-2.0-dev if libgirepository1.0-dev is not available.",
      "The install script adds you to the input group for Wayland hotkeys; log out and back in afterwards.",
      "If the hotkey or typing does not work in your session, enable Settings → Shortcuts → External Activation (Desktop Shortcut) and bind a desktop shortcut to vocalinux --toggle (toggle only, no push-to-talk), or dictate into the Dictation Pad and copy the text out.",
      "whisper.cpp uses a Vulkan GPU when available; check with vulkaninfo --summary.",
    ],
    postInstallChecks: [...COMMON_CHECKS],
  },
};

const distroKeywords: Record<DistroSlug, string[]> = {
  ubuntu: [
    "ubuntu voice dictation",
    "speech to text ubuntu",
    "ubuntu voice typing",
    "offline dictation ubuntu",
  ],
  debian: [
    "debian voice dictation",
    "speech to text debian",
    "debian voice typing",
    "offline dictation debian",
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
    "vocalinux aur",
  ],
  opensuse: [
    "opensuse voice dictation",
    "speech to text opensuse tumbleweed",
    "opensuse voice typing",
    "offline dictation opensuse",
  ],
  "linux-mint": [
    "linux mint voice dictation",
    "speech to text linux mint",
    "linux mint voice typing",
    "cinnamon dictation",
  ],
  "pop-os": [
    "pop os voice dictation",
    "speech to text pop!_os",
    "pop os voice typing",
    "offline dictation pop os",
  ],
};

const isDistroSlug = (value: string): value is DistroSlug => {
  return value in distroConfig;
};

const resolveParams = async (
  params: DistroParams,
): Promise<{ distro: string }> => {
  return Promise.resolve(params);
};

const getDistroStyles = (distro: DistroSlug) => {
  switch (distro) {
    case "ubuntu":
      return {
        icon: Laptop,
        iconClass: "text-primary",
        chipClass: "border-border bg-muted text-muted-foreground",
        panelClass: "bg-primary/10",
      };
    case "debian":
      return {
        icon: Server,
        iconClass: "text-primary",
        chipClass: "border-border bg-muted text-muted-foreground",
        panelClass: "bg-primary/10",
      };
    case "fedora":
      return {
        icon: Sparkles,
        iconClass: "text-primary",
        chipClass: "border-border bg-primary/10 text-primary",
        panelClass: "bg-primary/10",
      };
    case "opensuse":
      return {
        icon: RefreshCw,
        iconClass: "text-primary",
        chipClass: "border-border bg-primary/10 text-primary",
        panelClass: "bg-primary/10",
      };
    case "linux-mint":
      return {
        icon: Monitor,
        iconClass: "text-primary",
        chipClass: "border-border bg-muted text-muted-foreground",
        panelClass: "bg-primary/10",
      };
    case "pop-os":
      return {
        icon: Laptop,
        iconClass: "text-primary",
        chipClass: "border-border bg-primary/10 text-primary",
        panelClass: "bg-primary/10",
      };
    case "arch":
    default:
      return {
        icon: Cpu,
        iconClass: "text-primary",
        chipClass: "border-border bg-primary/10 text-muted-foreground",
        panelClass: "bg-primary/10",
      };
  }
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
        "Install Vocalinux on Linux with distro-specific setup instructions for Ubuntu, Debian, Fedora, Arch, openSUSE, Linux Mint, and Pop!_OS.",
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

      <section>
        <p
          className={`mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium ${styles.chipClass}`}
        >
          <DistroIcon className={`h-4 w-4 ${styles.iconClass}`} />
          {config.name} Setup Guide
        </p>

        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          {config.title}
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          {config.intro}
        </p>

        <div
          className={`rounded-[12px] border border-border p-6 ${styles.panelClass}`}
        >
          <h2 className="mb-3 inline-flex items-center gap-2 text-xl font-semibold">
            <Terminal className="h-5 w-5 text-primary" />
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
            <Sparkles className="h-5 w-5 text-primary" aria-hidden="true" />
            Supported on
          </h2>
          <ul className="space-y-2 text-muted-foreground">
            {config.supportedOn.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <CheckCircle2
                  className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
                  aria-hidden="true"
                />
                {item}
              </li>
            ))}
          </ul>
          <p className="mt-4 text-sm text-muted-foreground">
            Support levels come from the project&rsquo;s distribution
            compatibility matrix. They describe expected compatibility, not a
            list of test machines.
          </p>
        </article>
      </section>

      {config.otherInstallOptions.length > 0 && (
        <section className="mt-10 rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 inline-flex items-center gap-2 text-2xl font-semibold">
            <Download className="h-5 w-5 text-primary" aria-hidden="true" />
            Other install options for {config.name}
          </h2>
          <div className="space-y-6">
            {config.otherInstallOptions.map((option) => (
              <div key={option.label}>
                <h3 className="mb-2 font-semibold">{option.label}</h3>
                <p className="mb-3 text-sm text-muted-foreground">
                  {option.note}
                </p>
                <div className="rounded-[12px] bg-[color:var(--terminal)] p-4">
                  <code className="block overflow-x-auto whitespace-pre-wrap break-all text-sm text-[color:var(--terminal-fg)]">
                    {option.command}
                  </code>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-muted-foreground">
            Compare every package format on the
            <Link
              href="/install/"
              className="ml-1 font-semibold text-primary hover:underline"
            >
              install overview
            </Link>
            , or read the
            <Link
              href="/flatpak/"
              className="ml-1 font-semibold text-primary hover:underline"
            >
              Flatpak guide
            </Link>
            .
          </p>
        </section>
      )}

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

      <section className="/70 mt-10 rounded-[12px] border border-border bg-muted p-6">
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
          <Link
            href="/compare/"
            className="ml-1 font-semibold text-primary hover:underline"
          >
            engine comparison
          </Link>
          . Stuck? See
          <Link
            href="/troubleshooting/"
            className="ml-1 font-semibold text-primary hover:underline"
          >
            troubleshooting
          </Link>
          .
        </p>
      </section>
    </SeoSubpageShell>
  );
}
