import Link from "next/link";
import { type Metadata } from "next";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ChevronRight,
  Keyboard,
  Monitor,
  PanelTop,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { TerminalBlock } from "@/components/terminal-block";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/hyprland-sway";
const PAGE_TITLE = "Voice Typing on Hyprland, Sway and i3 for Linux";
const PAGE_DESCRIPTION =
  "Set up Vocalinux voice typing on sway, i3 and Hyprland: pick wtype, ydotool, IBus or the RemoteDesktop portal, bind keys over D-Bus, and use the Dictation Pad.";

const supportRows = [
  {
    name: "sway",
    status: "Good support",
    session: "Wayland",
    notes: "Wayland native, uses wtype",
  },
  { name: "i3", status: "Good support", session: "X11", notes: "Uses xdotool" },
  {
    name: "Hyprland",
    status: "Experimental",
    session: "Wayland",
    notes: "May need wtype configuration",
  },
];

const backendRows = [
  {
    backend: "IBus (ibus)",
    where:
      "Desktops that bridge IBus; on sway and Hyprland only with ibus-wayland running",
    needs:
      "IBus. On sway and Hyprland, Vocalinux skips IBus unless the ibus-wayland bridge is running",
  },
  {
    backend: "RemoteDesktop portal (portal)",
    where: "Wayland desktops whose portal implements RemoteDesktop",
    needs:
      "org.freedesktop.portal.RemoteDesktop. GNOME and KDE Plasma have it; most wlroots compositors do not",
  },
  {
    backend: "ydotool (ydotool)",
    where: "Any Wayland session",
    needs: "A usable /dev/uinput and a working ydotoold setup",
  },
  {
    backend: "wtype (wtype)",
    where: "sway, Hyprland and other virtual-keyboard compositors",
    needs: "The wtype package",
  },
  {
    backend: "xdotool (xdotool)",
    where: "i3 and other X11 sessions; XWayland windows only on Wayland",
    needs: "The xdotool package",
  },
];

const steps = [
  {
    name: "Install Vocalinux and the typing tools",
    text: "Install Vocalinux, then make sure wtype and wl-clipboard are installed on sway or Hyprland, or xdotool on i3.",
  },
  {
    name: "Check that the tool can type",
    text: 'Focus a text field and run wtype "hello" on Wayland or xdotool type "hello" on X11. If nothing appears, Vocalinux cannot type there either.',
  },
  {
    name: "Choose how dictation starts",
    text: "Either add yourself to the input group for the built-in hotkey, or turn on External Activation and bind vocalinux --toggle in your compositor config.",
  },
  {
    name: "Pin a backend if autodetection guesses wrong",
    text: "Set text_injection.backend in ~/.config/vocalinux/config.json, for example to wtype, then restart Vocalinux.",
  },
];

const faqs = [
  {
    question:
      "Why does dictation work in my browser but not in native Wayland apps?",
    answer:
      "That is the classic IBus symptom: the compositor does not relay IBus commits to native Wayland clients, so IBus reports success while nothing appears. Pin the wtype backend and restart Vocalinux.",
  },
  {
    question: "Does the RemoteDesktop portal work on sway or Hyprland?",
    answer:
      "Only if your portal backend implements org.freedesktop.portal.RemoteDesktop. GNOME and KDE Plasma do and most wlroots compositors do not. When it is missing, Vocalinux moves on to ydotool and then wtype.",
  },
  {
    question: "Can I use push-to-talk on a tiling compositor?",
    answer:
      "Yes, with the built-in listener, which on Wayland needs your user in the input group. A compositor keybind over D-Bus can only toggle dictation.",
  },
  {
    question: "Is Hyprland supported?",
    answer:
      "Hyprland is marked Experimental in the compatibility table and may need wtype configuration. sway and i3 are marked as good support.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: `${PAGE_TITLE} | Vocalinux`,
  description: PAGE_DESCRIPTION,
  path: PAGE_PATH,
  keywords: [
    "hyprland voice typing",
    "sway speech to text",
    "i3 voice dictation",
    "wtype dictation",
    "wayland tiling compositor dictation",
    "hyprland dictation keybind",
    "ydotool voice typing",
  ],
});

function InlineCode({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground">
      {children}
    </code>
  );
}

function ConfigBlock({ label, children }: { label: string; children: string }) {
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 text-sm font-medium">{label}</figcaption>
      <pre className="subpage-terminal p-4 text-sm">
        <code>{children}</code>
      </pre>
    </figure>
  );
}

export default function HyprlandSwayPage() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "TechArticle",
        headline: PAGE_TITLE,
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
      },
      {
        "@type": "HowTo",
        name: "Set up Vocalinux voice typing on sway, i3 or Hyprland",
        step: steps.map((step, index) => ({
          "@type": "HowToStep",
          position: index + 1,
          name: step.name,
          text: step.text,
        })),
      },
      {
        "@type": "FAQPage",
        mainEntity: faqs.map((faq) => ({
          "@type": "Question",
          name: faq.question,
          acceptedAnswer: { "@type": "Answer", text: faq.answer },
        })),
      },
    ],
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <section>
        <p className="subpage-kicker">Tiling compositors</p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Voice typing on Hyprland, sway and i3
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Tiling setups are hand-built, so Vocalinux cannot assume the pieces a
          full desktop provides. This guide covers which text injection backend
          applies on each compositor, how to bind dictation to a key in your
          config, and the fallback that works when typing into other windows
          does not.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <Monitor className="h-5 w-5 text-primary" aria-hidden="true" />
          Support status
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Compositor / WM
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Status
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Session
                </th>
                <th scope="col" className="pb-3 font-semibold">
                  Notes
                </th>
              </tr>
            </thead>
            <tbody>
              {supportRows.map((row) => (
                <tr key={row.name} className="border-b border-border">
                  <th scope="row" className="py-3 pr-4 font-medium">
                    {row.name}
                  </th>
                  <td className="py-3 pr-4">{row.status}</td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.session}
                  </td>
                  <td className="py-3 text-muted-foreground">{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Status comes from the project&apos;s desktop compatibility table. For
          GNOME, KDE and the general Wayland picture, see{" "}
          <Link href="/wayland/" className="text-primary underline">
            voice dictation on Wayland
          </Link>
          .
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Text injection options
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Vocalinux picks a backend automatically. On Wayland, when IBus is not
          selected, it tries the RemoteDesktop portal first, then ydotool, then
          wtype, and finally xdotool for XWayland windows. sway and Hyprland are
          on its list of compositors that do not bridge IBus to native Wayland
          apps, so IBus is skipped there unless the{" "}
          <InlineCode>ibus-wayland</InlineCode> helper (IBus 1.5.32 and newer)
          is running.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Backend (config value)
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Where it applies
                </th>
                <th scope="col" className="pb-3 font-semibold">
                  Needs
                </th>
              </tr>
            </thead>
            <tbody>
              {backendRows.map((row) => (
                <tr
                  key={row.backend}
                  className="border-b border-border align-top"
                >
                  <th scope="row" className="py-3 pr-4 font-medium">
                    {row.backend}
                  </th>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.where}
                  </td>
                  <td className="py-3 text-muted-foreground">{row.needs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 mt-6 font-semibold">Pin a backend</h3>
        <p className="mb-3 text-sm text-muted-foreground">
          Edit <InlineCode>~/.config/vocalinux/config.json</InlineCode> and
          restart Vocalinux. An explicit non-IBus value skips IBus selection. If
          the pinned tool is missing, Vocalinux warns and falls back to its
          normal order.
        </p>
        <ConfigBlock label="config.json">
          {`{
  "text_injection": {
    "backend": "wtype"
  }
}`}
        </ConfigBlock>
        <p className="mb-3 mt-4 text-sm text-muted-foreground">
          To try a backend for one run without saving it:
        </p>
        <TerminalBlock
          command="VOCALINUX_FORCE_BACKEND=wtype vocalinux --debug"
          displayCommand="VOCALINUX_FORCE_BACKEND=wtype vocalinux --debug"
        />
        <h3 className="mb-2 mt-6 font-semibold">Terminals</h3>
        <p className="text-sm text-muted-foreground">
          When text goes in through the clipboard, Vocalinux sends Ctrl+V in
          normal fields and Ctrl+Shift+V in terminal windows. Terminal detection
          works on Hyprland, sway and niri.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Setup steps
        </h2>
        <ol className="space-y-4">
          {steps.map((step, index) => (
            <li
              key={step.name}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <div className="mb-2 flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {index + 1}
                </span>
                <h3 className="font-semibold">{step.name}</h3>
              </div>
              <p className="ml-10 text-sm text-muted-foreground">{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <Keyboard className="h-5 w-5 text-primary" aria-hidden="true" />
          Keybinds via D-Bus
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          On Wayland the built-in hotkey reads{" "}
          <InlineCode>/dev/input</InlineCode>, so your user must be in the{" "}
          <InlineCode>input</InlineCode> group (the source installer does this;
          .deb and .rpm packages cannot). The alternative, added in v0.18.0, is
          to turn on Settings → Shortcuts → External Activation (Desktop
          Shortcut) and let the compositor own the key. These binds toggle
          dictation; they cannot do push-to-talk.
        </p>
        <div className="mb-4 grid gap-4 md:grid-cols-2">
          <ConfigBlock label="sway or i3 config">
            {"bindsym $mod+Shift+d exec vocalinux --toggle"}
          </ConfigBlock>
          <ConfigBlock label="hyprland.conf">
            {"bind = SUPER SHIFT, D, exec, vocalinux --toggle"}
          </ConfigBlock>
        </div>
        <p className="mb-3 text-sm text-muted-foreground">
          Or keep the built-in listener and join the group, then log out and
          back in:
        </p>
        <TerminalBlock
          command="sudo usermod -aG input $USER"
          displayCommand="sudo usermod -aG input $USER"
        />
        <p className="mt-4 text-sm text-muted-foreground">
          The full D-Bus interface and Flatpak command are in{" "}
          <Link href="/global-shortcuts/" className="text-primary underline">
            global shortcuts
          </Link>
          . Minimal window-manager sessions may also need their own autostart
          line; see{" "}
          <Link href="/autostart/" className="text-primary underline">
            autostart
          </Link>
          .
        </p>
      </section>

      <section className="bg-primary/5 mb-12 rounded-[12px] border border-border p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <PanelTop className="h-5 w-5 text-primary" aria-hidden="true" />
          The Dictation Pad fallback
        </h2>
        <p className="text-sm text-muted-foreground">
          If no backend types reliably on your setup, send dictation to the
          Dictation Pad instead (added in v0.18.0). It is an in-app window that
          receives the text, and you copy it out by hand, so no injection path
          is involved. Turn on Settings → Dictation → Dictate into Dictation
          Pad, then open it with Open Dictation Pad in the same group or
          Dictation Pad in the tray menu. Later releases fixed the pad ghosting
          away when idle under a Wayland compositor (v0.18.1) and stopped it
          travelling between workspaces with Settings (v0.18.5). Details on the{" "}
          <Link href="/dictation-pad/" className="text-primary underline">
            Dictation Pad page
          </Link>
          .
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <AlertTriangle className="h-5 w-5 text-primary" aria-hidden="true" />
          Troubleshooting
        </h2>
        <h3 className="mb-2 font-semibold">Nothing is typed anywhere</h3>
        <p className="mb-3 text-sm text-muted-foreground">
          Install the Wayland tools and test them by hand, then run Vocalinux
          with debug logging and check which backend it reports. The startup log
          records a pin request; a live test in the target app is the real
          confirmation.
        </p>
        <div className="mb-3">
          <TerminalBlock
            command="sudo apt install wtype wl-clipboard xclip xsel"
            displayCommand="sudo apt install wtype wl-clipboard xclip xsel"
          />
        </div>
        <div className="mb-6">
          <TerminalBlock
            command={'wtype "hello"'}
            displayCommand={'wtype "hello"'}
          />
        </div>
        <h3 className="mb-2 font-semibold">
          ydotool is chosen but does nothing
        </h3>
        <p className="mb-6 text-sm text-muted-foreground">
          ydotool needs <InlineCode>/dev/uinput</InlineCode> and a running
          ydotoold. Fix that setup or pin <InlineCode>wtype</InlineCode>.
        </p>
        <h3 className="mb-2 font-semibold">The hotkey never fires</h3>
        <p className="text-sm text-muted-foreground">
          Confirm you are in the <InlineCode>input</InlineCode> group in the
          current session, or switch to External Activation with a compositor
          bind. On i3 (X11) the built-in X11 listener handles the hotkey without
          that group.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">FAQ</h2>
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
        <p className="mt-4 text-sm text-muted-foreground">
          More help:{" "}
          <Link href="/troubleshooting/" className="text-primary underline">
            troubleshooting
          </Link>{" "}
          and{" "}
          <Link href="/desktop-reliability/" className="text-primary underline">
            desktop reliability
          </Link>
          .
        </p>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Dictate on your tiling setup
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux, check that wtype or xdotool can type, and bind
          dictation to a key in your compositor config.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/install/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Install Vocalinux
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Link>
          <Link
            href="/wayland/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Wayland guide
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
