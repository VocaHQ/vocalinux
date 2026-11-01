import Link from "next/link";
import { type Metadata } from "next";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Download,
  Keyboard,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/flatpak";
const PAGE_TITLE = "Install Vocalinux via Flatpak (VocaHQ Remote) | Vocalinux";
const PAGE_DESCRIPTION =
  "Install Vocalinux from the signed VocaHQ Flatpak remote (not Flathub): exact commands, updates, sandbox and Wayland notes, what is included, and uninstall.";

const FLATPAKREF_COMMAND =
  "flatpak install https://vocahq.github.io/vocalinux-flatpak/com.vocalinux.Vocalinux.flatpakref";

const MANUAL_COMMANDS = `flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-add --if-not-exists vocahq https://vocahq.github.io/vocalinux-flatpak/vocahq.flatpakrepo
flatpak install vocahq com.vocalinux.Vocalinux`;

const DBUS_TOGGLE_COMMAND =
  "gdbus call --session --dest com.vocalinux.Vocalinux --object-path /com/vocalinux/Vocalinux --method com.vocalinux.Vocalinux.Toggle";

const OVERRIDE_COMMAND =
  "flatpak override --user --nodevice=all --device=dri com.vocalinux.Vocalinux";

const RUN_COMMAND = "flatpak run com.vocalinux.Vocalinux";

const installSteps = [
  {
    name: "Install from the VocaHQ remote",
    text: `Run ${FLATPAKREF_COMMAND}. The .flatpakref adds the vocahq remote and resolves the GNOME runtime (org.gnome.Platform//50) through Flathub, so no separate Flathub setup is needed.`,
  },
  {
    name: "Or add the remotes by hand",
    text: "If you prefer explicit remotes, add flathub, add vocahq, then install com.vocalinux.Vocalinux from vocahq with the three commands below.",
  },
  {
    name: "Start Vocalinux",
    text: `Launch Vocalinux from your app menu or run ${RUN_COMMAND}.`,
  },
  {
    name: "Download a speech model",
    text: "Pick a model in Settings → Speech Model. Since v0.18.4 Vocalinux shows the download size and asks before downloading anything.",
  },
];

const faqs = [
  {
    question: "Is Vocalinux on Flathub?",
    answer:
      "No. The Flathub submission was closed on policy grounds in July 2026 and the project is not re-submitting. The app comes from the self-hosted vocahq remote; only the GNOME runtime is pulled from Flathub.",
  },
  {
    question: "Does the Flatpak update itself?",
    answer:
      "Flatpak updates it, not the app. Run flatpak update (or let your software center do it) and each stable release arrives as an incremental delta. Prerelease tags never reach the remote, and GitHub Release .flatpak bundles do not auto-update.",
  },
  {
    question: "Can I use Parakeet or Faster Whisper in the Flatpak?",
    answer:
      "No. The Flatpak ships whisper.cpp only. Faster Whisper, Parakeet, OpenAI Whisper and VOSK are available through the install script or a source install.",
  },
  {
    question: "My push-to-talk key does nothing on Wayland. Why?",
    answer:
      "On Wayland the built-in hotkey reads /dev/input. The manifest grants --device=all by default; if you removed device access with flatpak override, grant --device=input (Flatpak 1.15.6 or newer) or --device=all again, or enable External Activation and bind a desktop shortcut to the D-Bus Toggle command. Desktop shortcuts only toggle.",
  },
  {
    question: "Can I start a local VocaGateway from the Flatpak?",
    answer:
      "No. The sandbox cannot reach the host podman or docker socket. Start VocaGateway on the host yourself and point Settings → Remote Server at it, or use the installer or AppImage. Either way, audio leaves Vocalinux for the endpoint you configured, and leaves the machine if that endpoint is elsewhere. VocaGateway is not on-device, so keep it on localhost, a trusted LAN, an encrypted private network such as Tailscale, or HTTPS.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  path: PAGE_PATH,
  keywords: [
    "vocalinux flatpak",
    "linux voice dictation flatpak",
    "flatpak speech to text",
    "vocahq flatpak remote",
    "com.vocalinux.Vocalinux",
    "flatpak dictation wayland",
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

export default function FlatpakPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Install Vocalinux with Flatpak from the VocaHQ remote",
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
    name: "Install Vocalinux from the VocaHQ Flatpak remote",
    description: PAGE_DESCRIPTION,
    tool: [{ "@type": "HowToTool", name: "Flatpak" }],
    step: installSteps.map((step) => ({
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
        <p className="subpage-kicker">Flatpak remote added in v0.18.0</p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Install Vocalinux with Flatpak
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux publishes a signed, self-hosted Flatpak remote called{" "}
          <code>vocahq</code> on every stable release. It is{" "}
          <strong>not on Flathub</strong>: the app comes from VocaHQ, and only
          the GNOME runtime comes from Flathub. Install once, and{" "}
          <code>flatpak update</code> picks up each new release.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Who the Flatpak is for
        </h2>
        <p className="mb-3 text-muted-foreground">
          Pick the Flatpak if your distribution already uses Flatpak, if you run
          an immutable or non-standard layout, or if you want updates handled by
          the same tool as your other desktop apps. It runs on x86_64 and
          aarch64, and it ships the default whisper.cpp engine with Vulkan GPU
          support.
        </p>
        <p className="text-muted-foreground">
          Pick the <Link href="/install/">install script</Link> instead if you
          want Faster Whisper, Parakeet, OpenAI Whisper or VOSK, or the local
          VocaGateway launcher. Those are not in the Flatpak.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <Download className="h-5 w-5 text-primary" aria-hidden="true" />
          Install from the VocaHQ remote
        </h2>
        <ol className="space-y-6">
          <li className="rounded-[12px] border border-border bg-background p-5">
            <h3 className="font-semibold">1. {installSteps[0].name}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              One command. The <code>.flatpakref</code> adds the{" "}
              <code>vocahq</code> remote and resolves the GNOME runtime (
              <code>org.gnome.Platform//50</code>) through Flathub, so no
              separate Flathub setup is needed.
            </p>
            <Commands>{FLATPAKREF_COMMAND}</Commands>
          </li>
          <li className="rounded-[12px] border border-border bg-background p-5">
            <h3 className="font-semibold">2. {installSteps[1].name}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              If you prefer explicit remotes, add flathub, add vocahq, then
              install <code>com.vocalinux.Vocalinux</code> from vocahq:
            </p>
            <Commands>{MANUAL_COMMANDS}</Commands>
          </li>
          <li className="rounded-[12px] border border-border bg-background p-5">
            <h3 className="font-semibold">3. {installSteps[2].name}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Launch Vocalinux from your app menu, or run:
            </p>
            <Commands>{RUN_COMMAND}</Commands>
          </li>
          <li className="rounded-[12px] border border-border bg-background p-5">
            <h3 className="font-semibold">4. {installSteps[3].name}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Pick a model in Settings → Speech Model. Since v0.18.4 Vocalinux
              shows the download size and asks before downloading anything.
              After that one download, the whisper.cpp engine transcribes on
              your machine. Then hold Right Alt and speak.
            </p>
          </li>
        </ol>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <RefreshCw className="h-5 w-5 text-primary" aria-hidden="true" />
          Updates
        </h2>
        <p className="mb-3 text-muted-foreground">
          Every stable <code>v*</code> tag is imported into the remote, signed
          with the VocaHQ GPG key and published with static deltas, so an update
          downloads only what changed:
        </p>
        <Commands>flatpak update</Commands>
        <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
          <li>
            Alpha, beta and rc tags never reach the remote. The only Flatpak for
            a prerelease is the <code>.flatpak</code> bundle on GitHub Releases.
          </li>
          <li>
            Release bundles (
            <code>Vocalinux-&lt;version&gt;-x86_64.flatpak</code> or{" "}
            <code>-aarch64.flatpak</code>) do not auto-update. Switch to the
            remote if you installed one.
          </li>
          <li>
            The in-app update checker only tells you a release exists; it never
            installs anything.
          </li>
        </ul>
        <h3 className="mb-2 mt-6 font-semibold">
          If an update fails signature verification
        </h3>
        <p className="text-sm text-muted-foreground">
          After a signing-key rotation, existing installs must import the new
          public key. Re-running <code>remote-add</code> does not replace it.
          The documented fix:
        </p>
        <Commands>{`curl -fsSL https://vocahq.github.io/vocalinux-flatpak/vocahq.gpg -o /tmp/vocahq.gpg
flatpak remote-modify --gpg-import=/tmp/vocahq.gpg vocahq
flatpak update`}</Commands>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          What the Flatpak includes and leaves out
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Feature</th>
                <th className="pb-3 pr-4 font-semibold">In the Flatpak?</th>
                <th className="pb-3 font-semibold">Notes</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border">
                <td className="py-3 pr-4 font-medium">whisper.cpp engine</td>
                <td className="py-3 pr-4">Yes</td>
                <td className="py-3 text-muted-foreground">
                  Built with Vulkan; the GPU is reached through{" "}
                  <code>--device=dri</code>
                </td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-3 pr-4 font-medium">Silero neural VAD</td>
                <td className="py-3 pr-4">Yes</td>
                <td className="py-3 text-muted-foreground">
                  onnxruntime bundled since v0.18.4
                </td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-3 pr-4 font-medium">Remote API engine</td>
                <td className="py-3 pr-4">Yes</td>
                <td className="py-3 text-muted-foreground">
                  Audio leaves the machine for the endpoint you configure
                </td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-3 pr-4 font-medium">
                  Faster Whisper, Parakeet, OpenAI Whisper, VOSK
                </td>
                <td className="py-3 pr-4">No</td>
                <td className="py-3 text-muted-foreground">
                  Use the install script or a source install
                </td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-3 pr-4 font-medium">
                  Local VocaGateway launcher
                </td>
                <td className="py-3 pr-4">No</td>
                <td className="py-3 text-muted-foreground">
                  The sandbox cannot reach the host podman or docker socket
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Config and models live under{" "}
          <code>~/.var/app/com.vocalinux.Vocalinux/</code>, not{" "}
          <code>~/.config/vocalinux</code>.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <Keyboard className="h-5 w-5 text-primary" aria-hidden="true" />
          Sandbox permissions and Wayland
        </h2>
        <p className="mb-3 text-muted-foreground">
          The manifest asks for the microphone (<code>--socket=pulseaudio</code>
          ), the GPU (<code>--device=dri</code>), network for model downloads,
          the Wayland and X11 sockets, IBus and the tray watcher on D-Bus, and{" "}
          <code>--device=all</code> for keyboard devices and{" "}
          <code>/dev/uinput</code>. Flatpak has no narrower flag for uinput.
        </p>
        <h3 className="mb-2 mt-6 font-semibold">Hotkeys</h3>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li>
            Native X11: since v0.18.4 the Flatpak uses the X11 listener, so the
            hotkey needs no device access. GNOME on X11 is the exception and
            still needs <code>/dev/input</code>.
          </li>
          <li>
            Wayland: the built-in hotkey reads <code>/dev/input</code>. If you
            tighten permissions, grant <code>--device=input</code> on Flatpak
            1.15.6 or newer, or <code>--device=all</code> on older versions.
          </li>
          <li>
            No device access at all: enable Settings → Shortcuts → External
            Activation (Desktop Shortcut) and bind a desktop shortcut to the
            D-Bus Toggle command below. Desktop shortcuts toggle dictation; they
            cannot do push-to-talk.
          </li>
        </ul>
        <Commands>{DBUS_TOGGLE_COMMAND}</Commands>
        <p className="mt-3 text-sm text-muted-foreground">
          To drop device access but keep the GPU for whisper.cpp:
        </p>
        <Commands>{OVERRIDE_COMMAND}</Commands>
        <h3 className="mb-2 mt-6 font-semibold">Typing text</h3>
        <p className="text-sm text-muted-foreground">
          Text injection prefers the RemoteDesktop portal, which asks for
          permission once and handles non-US layouts. When the portal is
          unavailable it falls back to <code>wl-copy</code> plus ydotool paste,
          then xdotool for X11 and XWayland clients. Without{" "}
          <code>/dev/uinput</code> the ydotool fallback is gone, but the portal
          and xdotool remain. On KDE Plasma Wayland, set System Settings →
          Keyboard → Virtual Keyboard to &ldquo;IBus Wayland&rdquo;. On GNOME,
          the tray icon needs the AppIndicator extension. For more, see{" "}
          <Link href="/wayland/">Wayland voice typing</Link> and{" "}
          <Link href="/global-shortcuts/">global shortcuts via D-Bus</Link>.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <XCircle className="h-5 w-5 text-primary" aria-hidden="true" />
          Uninstall
        </h2>
        <p className="mb-3 text-muted-foreground">
          The <code>uninstall.sh</code> script is for script and source
          installs. For the Flatpak, use Flatpak itself. Remove the app:
        </p>
        <Commands>flatpak uninstall com.vocalinux.Vocalinux</Commands>
        <p className="mt-3 text-sm text-muted-foreground">
          Add <code>--delete-data</code> to also remove settings and downloaded
          models under <code>~/.var/app/com.vocalinux.Vocalinux/</code>. If no
          other app uses the remote, drop it too:
        </p>
        <Commands>flatpak remote-delete vocahq</Commands>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <CircleHelp className="h-5 w-5 text-primary" aria-hidden="true" />
          Flatpak FAQ
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
        <p className="mt-6 inline-flex items-start gap-2 text-sm text-muted-foreground">
          <AlertTriangle
            className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
            aria-hidden="true"
          />
          <span>
            More fixes for hotkeys, audio and text injection are on the{" "}
            <Link href="/troubleshooting/">troubleshooting page</Link>. To keep
            the whole stack local, see the{" "}
            <Link href="/gpu-acceleration/">GPU acceleration guide</Link> and{" "}
            <Link href="/voice-activity-detection/">Silero VAD</Link>.
          </span>
        </p>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 inline-flex items-center gap-2 font-display text-2xl font-semibold">
          <ShieldCheck className="h-5 w-5 text-primary" aria-hidden="true" />
          Need a different package?
        </h2>
        <p className="mb-6 text-muted-foreground">
          The install script covers every engine, the AUR and Nix flake fit Arch
          and NixOS, and the .deb and .rpm suit Debian, Ubuntu and Fedora.
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
            href="/install/nixos/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Nix flake and NixOS module
          </Link>
          <Link
            href="/local-gateway/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Local VocaGateway
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
