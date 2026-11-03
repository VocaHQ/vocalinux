import Link from "next/link";
import { type Metadata } from "next";
import {
  AlertTriangle,
  Braces,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Settings2,
  Terminal,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/install/nixos";
const PAGE_TITLE = "Vocalinux on NixOS: Nix Flake and NixOS Module | Vocalinux";
const PAGE_DESCRIPTION =
  "Install Vocalinux on NixOS or any Nix system with the official flake: nix run, nix profile, the NixOS and Home Manager modules, Wayland groups and scope.";

const TRY_COMMANDS = `nix run github:VocaHQ/vocalinux        # try it
nix profile install github:VocaHQ/vocalinux`;

const NIXOS_SNIPPET = `{
  inputs.vocalinux.url = "github:VocaHQ/vocalinux";

  outputs = { nixpkgs, vocalinux, ... }: {
    nixosConfigurations.host = nixpkgs.lib.nixosSystem {
      modules = [
        vocalinux.nixosModules.vocalinux
        {
          programs.vocalinux.enable = true;
          users.users.you.extraGroups = [ "input" "uinput" ];
        }
      ];
    };
  };
}`;

const HOME_MANAGER_SNIPPET = `{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.home-manager.url = "github:nix-community/home-manager";
  inputs.home-manager.inputs.nixpkgs.follows = "nixpkgs";
  inputs.vocalinux.url = "github:VocaHQ/vocalinux";

  outputs = { nixpkgs, home-manager, vocalinux, ... }: {
    homeConfigurations.you = home-manager.lib.homeManagerConfiguration {
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      modules = [
        vocalinux.homeManagerModules.vocalinux
        { programs.vocalinux.enable = true; }
      ];
    };
  };
}`;

const flakeOutputs = [
  {
    output: "packages.<system>.vocalinux (also default)",
    purpose: "The Vocalinux package for x86_64-linux and aarch64-linux",
  },
  {
    output: "apps.<system>.vocalinux (also default)",
    purpose: "What nix run github:VocaHQ/vocalinux starts",
  },
  {
    output: "overlays.default",
    purpose: "Adds pkgs.vocalinux to your own nixpkgs",
  },
  {
    output: "nixosModules.vocalinux (also default)",
    purpose: "programs.vocalinux.enable and programs.vocalinux.package",
  },
  {
    output: "homeManagerModules.vocalinux (also default)",
    purpose: "The same programs.vocalinux options, per user",
  },
];

const moduleSteps = [
  {
    name: "Add the flake input",
    text: 'Add inputs.vocalinux.url = "github:VocaHQ/vocalinux" to your system flake.',
  },
  {
    name: "Import the module and enable it",
    text: "Add vocalinux.nixosModules.vocalinux to your modules and set programs.vocalinux.enable = true. The module installs the package and enables hardware.uinput.",
  },
  {
    name: "Add each dictating user to input and uinput",
    text: 'Set users.users.<name>.extraGroups = [ "input" "uinput" ] for Wayland shortcuts and ydotool typing. X11 sessions can skip this.',
  },
  {
    name: "Rebuild and log in again",
    text: "Rebuild your system as usual, then log out and back in so the new group membership applies.",
  },
];

const faqs = [
  {
    question: "Is NixOS supported?",
    answer:
      "Yes, through the Nix flake added in v0.18.2. The standard install.sh script does not work on NixOS because of the /nix/store layout, which is why the distro compatibility doc still lists NixOS as unsupported for that installer. Use the flake instead.",
  },
  {
    question: "Does the Nix package use my GPU?",
    answer:
      "The bundled pywhispercpp is built with the Vulkan backend, so whisper.cpp can use an AMD, Intel or NVIDIA GPU through Vulkan. It is also built with GGML_NATIVE=OFF, a portable baseline rather than -march=native.",
  },
  {
    question:
      "Can I use Parakeet, Faster Whisper, VOSK or OpenAI Whisper from the flake?",
    answer:
      "No. The flake packages whisper.cpp plus the Silero VAD extra. The other engines are not packaged because of the PyTorch footprint or because they are not in nixpkgs.",
  },
  {
    question: "Why do I need the input group?",
    answer:
      "On Wayland the built-in push-to-talk hotkey reads keyboard devices under /dev/input. Membership in input grants read access to every keyboard and pointer device, so the module leaves that choice to each user. The alternative is a compositor shortcut bound to the D-Bus Toggle command, which only toggles.",
  },
  {
    question: "How do I update?",
    answer:
      "Update the vocalinux input in your flake lock and rebuild, or upgrade your Nix profile. The in-app update checker only tells you a release exists; it never installs anything.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  path: PAGE_PATH,
  keywords: [
    "nixos voice dictation",
    "vocalinux nix flake",
    "nixos speech to text",
    "nixos module vocalinux",
    "home manager vocalinux",
    "nix whisper.cpp dictation",
  ],
});

function Commands({ children }: { children: string }) {
  return (
    <div className="subpage-terminal mt-3 p-4">
      <pre>
        <code>{children}</code>
      </pre>
    </div>
  );
}

export default function NixosInstallPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Install Vocalinux on NixOS with the Nix flake",
    description: PAGE_DESCRIPTION,
    dateModified: "2026-11-01",
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
    mainEntityOfPage: absoluteUrl(PAGE_PATH),
  };

  const howToJsonLd = {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: "Enable Vocalinux with the NixOS module",
    description: PAGE_DESCRIPTION,
    tool: [{ "@type": "HowToTool", name: "Nix with flakes" }],
    step: moduleSteps.map((step) => ({
      "@type": "HowToStep",
      name: step.name,
      text: step.text,
      url: absoluteUrl(PAGE_PATH),
    })),
  };

  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((faq) => ({
      "@type": "Question",
      name: faq.question,
      acceptedAnswer: { "@type": "Answer", text: faq.answer },
    })),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(howToJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">Added in v0.18.2</p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Install Vocalinux on NixOS with the Nix flake
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          The Vocalinux repository is a Nix flake. It builds the app against
          nixpkgs, ships a NixOS module and a Home Manager module, and wires
          every text-injection and clipboard tool onto the wrapped
          binary&rsquo;s PATH. Use it on NixOS, or on any Linux with Nix and
          flakes enabled.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <Terminal className="h-5 w-5 text-primary" aria-hidden="true" />
          Try it or install into a profile
        </h2>
        <p className="mb-3 text-muted-foreground">
          No configuration needed. <code>nix run</code> starts Vocalinux once;{" "}
          <code>nix profile install</code> keeps it in your user profile:
        </p>
        <Commands>{TRY_COMMANDS}</Commands>
        <p className="mt-4 text-sm text-muted-foreground">
          On a non-NixOS host, pair <code>nix profile install</code> with your
          distro&rsquo;s udev rule and group membership for{" "}
          <code>/dev/uinput</code> and <code>/dev/input</code> if you use
          Wayland.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <Settings2 className="h-5 w-5 text-primary" aria-hidden="true" />
          Enable the NixOS module
        </h2>
        <ol className="mb-6 space-y-3">
          {moduleSteps.map((step, index) => (
            <li
              key={step.name}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="font-semibold">
                {index + 1}. {step.name}
              </h3>
              <p className="mt-2 text-sm text-muted-foreground">{step.text}</p>
            </li>
          ))}
        </ol>
        <p className="text-sm text-muted-foreground">
          The documented flake, with <code>host</code> and <code>you</code>{" "}
          replaced by your hostname and user:
        </p>
        <Commands>{NIXOS_SNIPPET}</Commands>
        <p className="mt-4 text-sm text-muted-foreground">
          <code>hardware.uinput.enable</code>, which the module sets, loads the
          uinput kernel module, creates the <code>uinput</code> group and
          installs the matching udev rule. ydotool and the evdev backend&rsquo;s
          keyboard clone both open <code>/dev/uinput</code>. Group membership
          stays per user because <code>input</code> grants read access to every
          keyboard and pointer device.
        </p>

        <h3 className="mb-2 mt-8 font-semibold">Home Manager</h3>
        <p className="text-sm text-muted-foreground">
          <code>homeManagerModules.vocalinux</code> takes the same{" "}
          <code>programs.vocalinux</code> options and installs into your home
          profile. Device permissions are a system concern, so on NixOS keep the
          NixOS module (or the group lines) on the system side.
        </p>
        <Commands>{HOME_MANAGER_SNIPPET}</Commands>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <Braces className="h-5 w-5 text-primary" aria-hidden="true" />
          What the flake provides
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Flake output</th>
                <th className="pb-3 font-semibold">Use</th>
              </tr>
            </thead>
            <tbody>
              {flakeOutputs.map((row) => (
                <tr key={row.output} className="border-b border-border">
                  <td className="py-3 pr-4 font-mono text-xs">{row.output}</td>
                  <td className="py-3 text-muted-foreground">{row.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 mt-6 font-semibold">Included in the package</h3>
        <ul className="space-y-2 text-sm text-muted-foreground">
          {[
            "whisper.cpp (the default engine), with pywhispercpp built from its PyPI sdist with the Vulkan backend",
            "Silero neural VAD through onnxruntime (the [vad] extra)",
            "GTK 3, PyGObject and the AppIndicator typelib from nixpkgs",
            "xdotool, wtype, ydotool, wl-clipboard, xclip, xsel, xprop, setxkbmap, ibus, gdbus, notify-send, paplay, aplay and vulkaninfo on PATH",
            "A desktop entry and the app icon",
          ].map((item) => (
            <li key={item} className="flex items-start gap-2">
              <CheckCircle2
                className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
                aria-hidden="true"
              />
              {item}
            </li>
          ))}
        </ul>
        <h3 className="mb-2 mt-6 font-semibold">Not included</h3>
        <p className="text-sm text-muted-foreground">
          The <code>vosk</code>, <code>whisper</code>, <code>parakeet</code> and{" "}
          <code>faster_whisper</code> extras are not packaged, so{" "}
          <Link href="/parakeet/">Parakeet</Link> and{" "}
          <Link href="/faster-whisper/">Faster Whisper</Link> need the install
          script on another distro. The flake follows{" "}
          <code>nixos-unstable</code> and builds for x86_64-linux and
          aarch64-linux.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <AlertTriangle className="h-5 w-5 text-primary" aria-hidden="true" />
          Gotchas
        </h2>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li>
            Do not run <code>install.sh</code> on NixOS. It expects a
            conventional filesystem layout; the flake is the supported path.
          </li>
          <li>
            Speech models are not part of the Nix store. Vocalinux downloads one
            only after you confirm it, and shows the size first.
          </li>
          <li>
            On Wayland without <code>input</code> membership, the hotkey is
            disabled. Bind a compositor shortcut through{" "}
            <Link href="/global-shortcuts/">D-Bus activation</Link> instead; it
            toggles, it cannot push-to-talk.
          </li>
          <li>
            On KDE Plasma Wayland, set System Settings → Keyboard → Virtual
            Keyboard to &ldquo;IBus Wayland&rdquo;. More in the{" "}
            <Link href="/wayland/">Wayland guide</Link>.
          </li>
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <CircleHelp className="h-5 w-5 text-primary" aria-hidden="true" />
          NixOS FAQ
        </h2>
        <div className="space-y-4">
          {faqs.map((faq) => (
            <div
              key={faq.question}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 font-semibold">{faq.question}</h3>
              <p className="text-sm text-muted-foreground">{faq.answer}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Other ways to install
        </h2>
        <p className="mb-6 text-muted-foreground">
          Not on Nix? The install script, AUR, .deb, .rpm, AppImage and the
          VocaHQ Flatpak remote cover most other systems.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/install/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            All install options
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Link>
          <Link
            href="/flatpak/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Flatpak remote
          </Link>
          <Link
            href="/gpu-acceleration/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            GPU acceleration
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
