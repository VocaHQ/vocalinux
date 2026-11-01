import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Copy,
  Keyboard,
  Monitor,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/dictation-pad";

const howToSteps = [
  {
    name: "Turn on pad capture",
    text: "Open Settings from the tray menu, go to the Dictation page and, in the Output group, switch on Dictate into Dictation Pad.",
  },
  {
    name: "Open the pad",
    text: "Click Open on the Open Dictation Pad row, or choose Dictation Pad from the tray menu. A window titled Vocalinux Dictation Pad appears.",
  },
  {
    name: "Dictate as usual",
    text: "Use your normal dictation shortcut. Each finished segment is appended to the end of the pad instead of being typed into the focused app.",
  },
  {
    name: "Copy the text out",
    text: "Click Copy All to put the whole pad on the clipboard (the button briefly reads Copied), or select part of the text and copy it with your keyboard. Paste it into the app you are working in.",
  },
  {
    name: "Clear when done",
    text: "Click Clear to empty the pad for the next piece of writing.",
  },
];

const settingsRows = [
  {
    label: "Dictate into Dictation Pad",
    where: "Settings → Dictation → Output",
    key: "text_injection.dictate_to_pad",
    note: "Off by default. On routes every dictated segment into the pad.",
  },
  {
    label: "Open Dictation Pad",
    where: "Settings → Dictation → Output",
    key: "(button)",
    note: "Shows the pad window. The tray menu has the same Dictation Pad entry.",
  },
  {
    label: "Voice Commands",
    where: "Settings → Dictation → Output",
    key: "speech_recognition.voice_commands_enabled",
    note: "Needed if you want spoken editing commands to act on the pad.",
  },
  {
    label: "Copy to Clipboard",
    where: "Settings → Dictation → Output",
    key: "text_injection.copy_to_clipboard",
    note: "Separate option that copies each result to the clipboard. Not required for the pad.",
  },
];

const faqs = [
  {
    q: "Does the Dictation Pad save my text to disk?",
    a: "No. The pad keeps its text for the current session only. Closing the window hides it and keeps the text, but quitting Vocalinux discards it. Copy anything you want to keep before you quit.",
  },
  {
    q: "Why does the pad not stay on top of my other windows on Wayland?",
    a: "Vocalinux asks for the pad to float above other windows and appear on every workspace, which works on X11. Wayland has no always-on-top protocol for normal apps, so the compositor decides. If a covered pad stops drawing, choose Dictation Pad from the tray menu again and Vocalinux recreates the window.",
  },
  {
    q: "Do I still need IBus, ydotool or wtype?",
    a: "Not for getting text out. Pad capture skips cross-application text injection entirely. You still need a working dictation shortcut, which on Wayland means the built-in listener with access to input devices, or External Activation (Desktop Shortcut) with a desktop shortcut that runs vocalinux --toggle.",
  },
  {
    q: "Can I edit text inside the pad?",
    a: "Yes. The pad is an ordinary editable text box. You can type, fix words and delete lines by hand, and new dictation is still appended at the end.",
  },
  {
    q: "Do voice commands work in the pad?",
    a: "Yes, when Voice Commands is on. While pad capture is on, editing commands such as delete that, undo, redo, select all, cut, copy and paste act on the pad and never reach the app that has keyboard focus. Editing commands are English-only.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Dictation Pad: Wayland-Safe Voice Typing on Linux | Vocalinux",
  description:
    "Dictate into the Vocalinux Dictation Pad, then copy text out by hand. The Wayland-safe path that skips text injection. Setup, settings, limits and FAQ.",
  path: PAGE_PATH,
  keywords: [
    "Wayland voice typing",
    "Wayland dictation workaround",
    "Linux dictation pad",
    "voice typing without text injection",
    "Vocalinux Dictation Pad",
    "speech to text window Linux",
  ],
});

export default function DictationPadPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Dictation Pad: Wayland-Safe Voice Typing on Linux",
    description:
      "How the Vocalinux Dictation Pad receives dictation in its own window so text never depends on cross-application injection, and how to copy it out.",
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
    name: "Dictate into the Vocalinux Dictation Pad",
    step: howToSteps.map((step, index) => ({
      "@type": "HowToStep",
      position: index + 1,
      name: step.name,
      text: step.text,
    })),
  };

  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
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
        <p className="subpage-kicker">Added in v0.18.0</p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Dictation Pad: voice typing that skips text injection
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          The Dictation Pad is a small Vocalinux window with an editable text
          box. When pad capture is on, everything you dictate lands there
          instead of being typed into another app. You copy the text out
          yourself. Because nothing is injected into other windows, the
          compositor rules that make keystroke injection fragile on Wayland
          never come into play.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-3">
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Monitor className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Who it is for</h3>
          <p className="text-sm text-muted-foreground">
            Wayland users whose compositor blocks or garbles injected text, and
            anyone who wants to read and fix a draft before it reaches the real
            app.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Copy className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">How text gets out</h3>
          <p className="text-sm text-muted-foreground">
            Copy All puts the whole pad on the clipboard. You can also select
            part of the text and copy it like any other text box.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Keyboard className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">What stays the same</h3>
          <p className="text-sm text-muted-foreground">
            Your shortcut, engine, transcript corrections and post-processing
            script all work as before. Only the destination of the text changes.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Why the Dictation Pad exists
        </h2>
        <p className="mb-4 text-muted-foreground">
          On X11, Vocalinux types into the focused window with xdotool. Wayland
          deliberately stops apps from sending keystrokes to each other, so
          Vocalinux has to go through IBus, the RemoteDesktop portal, ydotool or
          wtype, and which of those works depends on your desktop. Most setups
          are covered (see the <Link href="/wayland/">Wayland guide</Link>), but
          some compositor and app combinations still drop or mangle text.
        </p>
        <p className="text-muted-foreground">
          The pad is the explicit fallback for those cases. Dictation is written
          straight into a Vocalinux window, so there is no injection step left
          to fail. Text bound for the pad also lands there even if you switched
          to another app while it was being transcribed.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          How to use it
        </h2>
        <ol className="space-y-4">
          {howToSteps.map((step, index) => (
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
          In v0.18.4 the switch moved to Settings → Dictation, next to the Open
          Dictation Pad button. On older 0.18 releases, update first; the{" "}
          <Link href="/changelog/">changelog</Link> lists what changed in each
          patch.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Settings it touches
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Setting</th>
                <th className="pb-3 pr-4 font-semibold">Where</th>
                <th className="pb-3 pr-4 font-semibold">config.json key</th>
                <th className="pb-3 font-semibold">What it does</th>
              </tr>
            </thead>
            <tbody>
              {settingsRows.map((row) => (
                <tr key={row.label} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{row.label}</td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.where}
                  </td>
                  <td className="py-3 pr-4">
                    <code>{row.key}</code>
                  </td>
                  <td className="py-3 text-muted-foreground">{row.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          The switch is stored in <code>~/.config/vocalinux/config.json</code>.
          Flipping it in Settings applies to the next dictated segment without a
          restart. The saved value looks like this:
        </p>
        <pre className="subpage-terminal mt-3 overflow-x-auto p-4">
          <code>{`{
  "text_injection": {
    "dictate_to_pad": true
  }
}`}</code>
        </pre>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Working inside the pad
        </h2>
        <h3 className="mb-2 font-semibold">Editing by hand and by voice</h3>
        <p className="mb-4 text-muted-foreground">
          The text box is editable, so you can fix a word with the keyboard
          between dictations. With Voice Commands on, spoken editing commands
          target the pad while capture is on: <em>delete that</em> removes the
          last dictated segment, <em>undo</em> and <em>redo</em> step through
          the pad&apos;s own history, and <em>select all</em>,{" "}
          <em>select line</em>, <em>select word</em>, <em>select paragraph</em>,{" "}
          <em>cut</em>, <em>copy</em> and <em>paste</em> work on the pad&apos;s
          text. They never reach the app that happens to have focus. The full
          command list is on the{" "}
          <Link href="/shortcuts/">voice commands page</Link>.
        </p>
        <h3 className="mb-2 font-semibold">
          Recent snippets as a second safety net
        </h3>
        <p className="text-muted-foreground">
          The tray&apos;s Recent Snippets menu keeps your last dictations (10 by
          default) in memory. Clicking one copies it to the clipboard, which
          helps when a single segment went to the wrong place.
        </p>
      </section>

      <section className="bg-primary/5 mb-12 rounded-[12px] border border-border p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Limitations and gotchas
        </h2>
        <ul className="space-y-3 text-sm text-muted-foreground">
          <li className="flex items-start gap-2">
            <CheckCircle2
              className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
              aria-hidden="true"
            />
            <span>
              <strong className="text-foreground">
                Copying out is manual.
              </strong>{" "}
              The pad never pastes for you. That extra step is the trade for not
              depending on injection.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2
              className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
              aria-hidden="true"
            />
            <span>
              <strong className="text-foreground">Session only.</strong> Text
              survives closing the window, not quitting the app.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2
              className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
              aria-hidden="true"
            />
            <span>
              <strong className="text-foreground">
                No always-on-top on Wayland.
              </strong>{" "}
              A covered, idle pad can be shelved by the compositor. Reopen it
              from the tray. v0.18.1 fixed the pad ghosting away, and v0.18.5
              stopped it travelling between workspaces with Settings.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2
              className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
              aria-hidden="true"
            />
            <span>
              <strong className="text-foreground">
                The shortcut still has to fire.
              </strong>{" "}
              The pad solves text output, not hotkeys. On Wayland the built-in
              listener needs access to <code>/dev/input</code>, or you can turn
              on External Activation (Desktop Shortcut) and bind{" "}
              <code>vocalinux --toggle</code> to a desktop shortcut (toggle
              only, no push-to-talk). See{" "}
              <Link href="/global-shortcuts/">global shortcuts</Link> and{" "}
              <Link href="/hyprland-sway/">Hyprland and sway</Link>.
            </span>
          </li>
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">FAQ</h2>
        <div className="space-y-4">
          {faqs.map((item) => (
            <div
              key={item.q}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 font-semibold">{item.q}</h3>
              <p className="text-sm text-muted-foreground">{item.a}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Try the Dictation Pad
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux, open Settings → Dictation and switch on Dictate
          into Dictation Pad. If injection already works on your desktop, the{" "}
          <Link href="/troubleshooting/">troubleshooting guide</Link> covers the
          other paths.
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
