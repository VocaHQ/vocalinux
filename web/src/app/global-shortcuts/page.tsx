import Link from "next/link";
import { type Metadata } from "next";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ChevronRight,
  Command,
  Keyboard,
  ShieldCheck,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { TerminalBlock } from "@/components/terminal-block";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/global-shortcuts";
const PAGE_TITLE = "Global Shortcuts for Voice Dictation via D-Bus";
const PAGE_DESCRIPTION =
  "Start and stop Vocalinux dictation from GNOME, KDE, sway or Hyprland shortcuts and scripts using its D-Bus service and the --toggle, --start and --stop flags.";

const GDBUS_TOGGLE =
  "gdbus call --session --dest com.vocalinux.Vocalinux --object-path /com/vocalinux/Vocalinux --method com.vocalinux.Vocalinux.Toggle";

const dbusRows = [
  { item: "Bus", value: "Session bus" },
  { item: "Bus name", value: "com.vocalinux.Vocalinux" },
  { item: "Object path", value: "/com/vocalinux/Vocalinux" },
  { item: "Interface", value: "com.vocalinux.Vocalinux" },
  { item: "Methods", value: "Toggle, Start, Stop (no arguments)" },
];

const commandRows = [
  {
    cli: "vocalinux --toggle",
    method: "Toggle",
    effect: "Start if idle, stop if active",
  },
  {
    cli: "vocalinux --start",
    method: "Start",
    effect: "Start voice typing; does nothing if already running",
  },
  {
    cli: "vocalinux --stop",
    method: "Stop",
    effect: "Stop voice typing; does nothing if already idle",
  },
];

const steps = [
  {
    name: "Turn on External Activation",
    text: "Open Settings → Shortcuts (the Keyboard Shortcuts group on the Dictation page) and turn on External Activation (Desktop Shortcut). It applies immediately and the built-in key listener stops.",
  },
  {
    name: "Pick the command",
    text: "On a native install, use vocalinux --toggle. On Flatpak, use the gdbus call shown below, because vocalinux --toggle is not on the host PATH.",
  },
  {
    name: "Bind it in your desktop",
    text: "Create a custom shortcut in GNOME or KDE, or a bind line in your sway or Hyprland config, that runs that command.",
  },
  {
    name: "Test it",
    text: "Focus a text field, press the shortcut, speak, then press it again to stop.",
  },
];

const faqs = [
  {
    question: "Can a desktop shortcut do push-to-talk?",
    answer:
      "No. A desktop shortcut only sends the key press and never the release, so it can toggle dictation but cannot hold-to-talk. Use the built-in listener if you need push-to-talk.",
  },
  {
    question: "Will vocalinux --toggle launch Vocalinux if it is not running?",
    answer:
      "No. It forwards the command to a running instance over D-Bus and exits. If no instance answers, it logs that it could not reach a running Vocalinux and exits with status 1.",
  },
  {
    question: "Do I still need the input group?",
    answer:
      "Not for starting and stopping dictation. With External Activation on, Vocalinux does not read /dev/input for the hotkey. Text injection is unaffected and keeps its own requirements.",
  },
  {
    question: "What happens if the D-Bus service cannot start?",
    answer:
      "Vocalinux shows an External activation unavailable notification and falls back to the internal keyboard shortcut, so you are never left without a way to start or stop dictation.",
  },
  {
    question: "Do per-language shortcuts work with External Activation?",
    answer:
      "No. Per-language shortcuts belong to the built-in listener, and the whole listener family stops when External Activation is on. Turn External Activation off to use them again.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: `${PAGE_TITLE} | Vocalinux`,
  description: PAGE_DESCRIPTION,
  path: PAGE_PATH,
  keywords: [
    "linux dictation global shortcut",
    "vocalinux d-bus",
    "vocalinux --toggle",
    "sway voice typing keybind",
    "hyprland dictation keybind",
    "kde global shortcut dictation",
    "gnome custom shortcut voice typing",
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

export default function GlobalShortcutsPage() {
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
        name: "Start Vocalinux dictation from a desktop shortcut",
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
        <p className="subpage-kicker">Added in v0.18.0</p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Start dictation from desktop shortcuts and scripts
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux can hand hotkey duty to your desktop. A running instance
          answers on the session D-Bus, so a GNOME or KDE custom shortcut, a
          sway or Hyprland bind, or any script can start and stop voice typing
          without Vocalinux reading your keyboard.
        </p>
      </section>

      <section className="mb-12 grid gap-4 md:grid-cols-3">
        <div className="rounded-[12px] border border-border bg-background p-5">
          <ShieldCheck
            className="mb-3 h-6 w-6 text-primary"
            aria-hidden="true"
          />
          <h2 className="mb-2 font-semibold">No /dev/input access</h2>
          <p className="text-sm text-muted-foreground">
            On Wayland the built-in listener reads{" "}
            <InlineCode>/dev/input</InlineCode>, which needs the{" "}
            <InlineCode>input</InlineCode> group. A compositor shortcut avoids
            that entirely.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Keyboard className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h2 className="mb-2 font-semibold">Toggle, not push-to-talk</h2>
          <p className="text-sm text-muted-foreground">
            Your desktop sends the key press only. Press once to start, press
            again to stop.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Command className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h2 className="mb-2 font-semibold">Scriptable</h2>
          <p className="text-sm text-muted-foreground">
            Separate Start and Stop methods let scripts set a known state
            instead of flipping it.
          </p>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          The D-Bus interface
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          These names come from <InlineCode>dbus_service.py</InlineCode> in the
          Vocalinux source.
        </p>
        <div className="mb-6 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <tbody>
              {dbusRows.map((row) => (
                <tr key={row.item} className="border-b border-border">
                  <th scope="row" className="py-3 pr-4 font-medium">
                    {row.item}
                  </th>
                  <td className="py-3 font-mono text-muted-foreground">
                    {row.value}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 font-semibold">CLI commands</h3>
        <div className="mb-6 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Command
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  D-Bus method
                </th>
                <th scope="col" className="pb-3 font-semibold">
                  Effect
                </th>
              </tr>
            </thead>
            <tbody>
              {commandRows.map((row) => (
                <tr key={row.cli} className="border-b border-border">
                  <td className="py-3 pr-4 font-mono">{row.cli}</td>
                  <td className="py-3 pr-4 font-mono text-muted-foreground">
                    {row.method}
                  </td>
                  <td className="py-3 text-muted-foreground">{row.effect}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 font-semibold">Calling D-Bus directly</h3>
        <p className="mb-3 text-sm text-muted-foreground">
          The <InlineCode>gdbus</InlineCode> form is what the Flatpak
          documentation recommends: it is immediate and does not start another
          sandbox on every press. Swap <InlineCode>Toggle</InlineCode> for{" "}
          <InlineCode>Start</InlineCode> or <InlineCode>Stop</InlineCode> as
          needed.
        </p>
        <TerminalBlock command={GDBUS_TOGGLE} displayCommand={GDBUS_TOGGLE} />
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">Set it up</h2>
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
        <p className="mt-4 text-sm text-muted-foreground">
          The same switch is stored as{" "}
          <InlineCode>shortcuts.disable_internal_hotkey</InlineCode> in{" "}
          <InlineCode>~/.config/vocalinux/config.json</InlineCode>. Quit
          Vocalinux before editing that file by hand, or the running app can
          overwrite your change.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Binding the shortcut on each desktop
        </h2>
        <p className="mb-6 text-sm text-muted-foreground">
          The key combination is your choice; the examples use Super+Shift+D.
          Only the command matters to Vocalinux. Menu names and config syntax
          belong to each desktop and can differ between versions.
        </p>
        <h3 className="mb-2 font-semibold">GNOME</h3>
        <p className="mb-6 text-sm text-muted-foreground">
          In Settings → Keyboard, open the custom shortcuts list, add a
          shortcut, enter <InlineCode>vocalinux --toggle</InlineCode> as the
          command and record your key combination.
        </p>
        <h3 className="mb-2 font-semibold">KDE Plasma</h3>
        <p className="mb-6 text-sm text-muted-foreground">
          Open System Settings → Keyboard → Shortcuts → Add New → Command or
          Script (older Plasma: System Settings → Shortcuts → Custom Shortcuts →
          Edit → New → Global Shortcut → Command/URL) and bind your keys to{" "}
          <InlineCode>vocalinux --toggle</InlineCode>.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <ConfigBlock label="sway (~/.config/sway/config)">
            {"bindsym $mod+Shift+d exec vocalinux --toggle"}
          </ConfigBlock>
          <ConfigBlock label="Hyprland (hyprland.conf)">
            {"bind = SUPER SHIFT, D, exec, vocalinux --toggle"}
          </ConfigBlock>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          If your compositor cannot find <InlineCode>vocalinux</InlineCode>, its
          PATH may not include <InlineCode>~/.local/bin</InlineCode>. Use the
          full path{" "}
          <InlineCode>~/.local/share/vocalinux/venv/bin/vocalinux</InlineCode>{" "}
          for an installer setup, or the <InlineCode>gdbus</InlineCode> command
          above. More on tiling compositors in{" "}
          <Link href="/hyprland-sway/" className="text-primary underline">
            voice typing on Hyprland and sway
          </Link>
          .
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <AlertTriangle className="h-5 w-5 text-primary" aria-hidden="true" />
          Limitations and gotchas
        </h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            Toggle only. Push-to-talk needs the key release, which a desktop
            shortcut never delivers.
          </li>
          <li>
            The command needs a session bus. From SSH or a systemd unit without{" "}
            <InlineCode>DBUS_SESSION_BUS_ADDRESS</InlineCode>, it fails with a
            non-zero exit.
          </li>
          <li>
            While a transcription is still processing, Toggle cancels it, the
            same as pressing the recording hotkey again (since v0.18.4).
          </li>
          <li>
            On Flatpak,{" "}
            <InlineCode>
              flatpak run com.vocalinux.Vocalinux --toggle
            </InlineCode>{" "}
            also works but starts a sandbox on each press; prefer{" "}
            <InlineCode>gdbus</InlineCode>.
          </li>
          <li>
            This changes how dictation starts, not how text is typed. If text
            does not appear, see{" "}
            <Link href="/wayland/" className="text-primary underline">
              Wayland text injection
            </Link>
            .
          </li>
        </ul>
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
          Related:{" "}
          <Link href="/shortcuts/" className="text-primary underline">
            shortcuts and voice commands
          </Link>
          ,{" "}
          <Link href="/gnome-kde/" className="text-primary underline">
            GNOME and KDE
          </Link>
          ,{" "}
          <Link href="/flatpak/" className="text-primary underline">
            Flatpak
          </Link>{" "}
          and{" "}
          <Link href="/troubleshooting/" className="text-primary underline">
            troubleshooting
          </Link>
          .
        </p>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Bind your dictation key
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux, turn on External Activation, and let your desktop
          own the shortcut.
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
            href="/hyprland-sway/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Hyprland and sway guide
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
