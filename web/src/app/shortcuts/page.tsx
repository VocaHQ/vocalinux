import Link from "next/link";
import { type Metadata } from "next";
import { ChevronRight, Keyboard, Mouse, Settings, Volume2, Zap } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const shortcutCategories = [
  {
    category: "Dictation Controls",
    icon: Mic,
    iconColor: "text-primary",
    shortcuts: [
      {
        keys: ["Hold Right Alt"],
        action: "Push-to-talk (default): speak while held",
        note: "Release to stop · Option on Mac-layout keyboards",
      },
      {
        keys: ["Double-tap key"],
        action: "Toggle mode: start/stop dictation",
        note: "Optional — switch in Settings",
      },
      {
        keys: ["Settings"],
        action: "Choose Left/Right Ctrl, Alt, or Shift in Settings",
        note: "Modifier key side selection",
      },
      {
        keys: ["PTT"],
        action: "v0.10.1+ includes fixes for premature transcription during PTT silence",
        note: "Improved push-to-talk reliability",
      },
    ],
  },
  {
    category: "Voice Commands",
    icon: Zap,
    iconColor: "text-primary",
    shortcuts: [
      { keys: ["\"new line\""], action: "Insert a new line", note: "Say this phrase" },
      { keys: ["\"new paragraph\""], action: "Insert a new paragraph", note: "Say this phrase" },
      { keys: ["\"delete that\""], action: "Delete last phrase", note: "Also: \"scratch that\"" },
      { keys: ["\"select all\""], action: "Select all text", note: "Voice command" },
      { keys: ["\"copy this\""], action: "Copy selection", note: "Voice command" },
      { keys: ["\"paste here\""], action: "Paste clipboard", note: "Voice command" },
      { keys: ["\"undo\""], action: "Undo last action", note: "Voice command" },
      { keys: ["\"redo\""], action: "Redo last action", note: "Voice command" },
      { keys: ["Settings Toggle"], action: "Enable/disable voice commands", note: "Optional in v0.8.0-beta" },
      {
        keys: ["Voice Commands"],
        action: "Voice commands are optional since v0.8.0 - auto-enabled for VOSK, disabled for Whisper by default",
        note: "Engine-specific defaults",
      },
    ],
  },
  {
    category: "Audio Feedback",
    icon: Volume2,
    iconColor: "text-primary",
    shortcuts: [
      {
        keys: ["Settings Toggle"],
        action: "Enable/disable sound effects from Settings dialog",
        note: "Audio feedback control",
      },
      {
        keys: ["v0.9.0+"],
        action: "Sound effects now toggleable - smooth gliding tones for start/stop",
        note: "Pleasant audio cues",
      },
    ],
  },
  {
    category: "Tray Icon Actions",
    icon: Mouse,
    iconColor: "text-primary",
    shortcuts: [
      { keys: ["Left Click"], action: "Toggle dictation", note: "On tray icon" },
      { keys: ["Right Click"], action: "Open context menu", note: "Settings, quit, etc." },
    ],
  },
  {
    category: "Configuration",
    icon: Settings,
    iconColor: "text-primary",
    shortcuts: [
      { keys: ["Config File"], action: "~/.config/vocalinux/config.json", note: "Manual editing" },
    ],
  },
];

function Mic(props: { className?: string }) {
  return (
    <svg className={props.className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
    </svg>
  );
}

export const metadata: Metadata = buildPageMetadata({
  title: "Keyboard Shortcuts & Voice Commands - Vocalinux",
  description:
    "Learn Vocalinux keyboard shortcut modes and voice commands. Use toggle mode or push-to-talk, then customize activation and command behavior.",
  path: "/shortcuts",
  keywords: [
    "vocalinux shortcuts",
    "linux voice dictation commands",
    "speech to text keyboard shortcuts",
    "voice commands linux",
  ],
});

export default function ShortcutsPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Vocalinux Keyboard Shortcuts & Voice Commands",
    description:
      "Complete guide to Vocalinux keyboard shortcuts and voice commands for efficient Linux voice dictation.",
    dateModified: "2026-03-30",
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
    mainEntityOfPage: absoluteUrl("/shortcuts"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Keyboard className="h-4 w-4" />
          Quick Reference
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Keyboard Shortcuts & Voice Commands
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Master Vocalinux with keyboard shortcuts and voice commands. New installs default to
          push-to-talk (hold Right Alt), or switch to toggle mode (double-tap), then apply voice
          commands for editing and formatting.
        </p>
      </section>

      {/* Quick Start */}
      <section className="mb-12 rounded-[12px] border border-primary/20 bg-primary/5 p-6">
        <h2 className="mb-4 text-xl font-semibold">Quick Start</h2>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <kbd className="rounded-lg border border-border bg-muted px-3 py-1.5 font-mono text-sm font-semibold">
              Hold Right Alt
            </kbd>
          </div>
          <span className="text-muted-foreground">→</span>
          <span className="font-medium">Push-to-Talk: Speak While Held</span>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          Right Alt is the Option key on Mac-layout keyboards. Toggle mode is also available:
          double-tap your configured key to start/stop. You can switch modes and keys in Settings.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Voice commands can be enabled or disabled from Settings depending on your workflow.
        </p>
      </section>

      {/* Shortcut Categories */}
      <section className="space-y-8">
        {shortcutCategories.map((category) => {
          const Icon = category.icon;
          return (
            <article
              key={category.category}
              className="rounded-[12px] border border-border bg-background p-6"
            >
              <h2 className="mb-6 flex items-center gap-3 font-display text-2xl font-semibold">
                <span className={`rounded-[12px] bg-muted p-2 bg-muted`}>
                  <Icon className={`h-5 w-5 ${category.iconColor}`} />
                </span>
                {category.category}
              </h2>

              <div className="space-y-4">
                {category.shortcuts.map((shortcut, index) => (
                  <div
                    key={index}
                    className="flex flex-wrap items-center justify-between gap-4 rounded-[12px] bg-muted p-4"
                  >
                    <div className="flex items-center gap-3">
                      {shortcut.keys.map((key, keyIndex) => (
                        <span key={keyIndex} className="flex items-center gap-2">
                          <kbd className="rounded-lg border border-border bg-muted px-3 py-1.5 font-mono text-sm font-semibold">
                            {key}
                          </kbd>
                          {keyIndex < shortcut.keys.length - 1 && (
                            <span className="text-muted-foreground">+</span>
                          )}
                        </span>
                      ))}
                    </div>
                    <div className="text-right">
                      <p className="font-medium">{shortcut.action}</p>
                      <p className="text-sm text-muted-foreground">{shortcut.note}</p>
                    </div>
                  </div>
                ))}
              </div>
            </article>
          );
        })}
      </section>

      {/* Customization */}
      <section className="mt-12 rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Customizing Shortcuts</h2>
        <p className="mb-4 text-muted-foreground">
          You can customize the activation shortcut in the settings panel or by editing the
          configuration file directly:
        </p>
        <div className="rounded-lg bg-[color:var(--terminal)] p-4">
          <code className="text-sm text-[color:var(--terminal-fg)]">~/.config/vocalinux/config.json</code>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Open Vocalinux and access Settings from the tray icon to change keyboard shortcuts
          through the GUI.
        </p>
      </section>

      {/* Related Pages */}
      <section className="mt-12 grid gap-6 md:grid-cols-2">
        <Link
          href="/faq/"
          className="group rounded-[12px] border border-border bg-background p-6 transition-all"
        >
          <h3 className="mb-2 text-xl font-semibold">Frequently Asked Questions</h3>
          <p className="text-sm text-muted-foreground">
            Get answers to common questions about Vocalinux features and usage.
          </p>
          <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-primary">
            View FAQ
            <ChevronRight className="h-4 w-4" />
          </span>
        </Link>

        <Link
          href="/troubleshooting/"
          className="group rounded-[12px] border border-border bg-background p-6 transition-all"
        >
          <h3 className="mb-2 text-xl font-semibold">Troubleshooting</h3>
          <p className="text-sm text-muted-foreground">
            Having issues? Find solutions to common problems and fixes.
          </p>
          <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-primary">
            Get Help
            <ChevronRight className="h-4 w-4" />
          </span>
        </Link>
      </section>
    </SeoSubpageShell>
  );
}
