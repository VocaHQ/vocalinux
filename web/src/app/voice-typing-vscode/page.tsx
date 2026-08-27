import Link from "next/link";
import { type Metadata } from "next";
import {
  Bug,
  CheckCircle2,
  ChevronRight,
  Code2,
  Keyboard,
  Lightbulb,
  MessageSquare,
  Mic,
  ToggleLeft,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const setupSteps = [
  {
    title: "Install Vocalinux",
    description:
      "Follow the install guide, launch Vocalinux, and confirm your microphone and language are configured.",
    href: "/install/",
    linkLabel: "Open installation guide",
    icon: CheckCircle2,
  },
  {
    title: "Configure your activation shortcut",
    description:
      "Pick a shortcut that does not conflict with VS Code keybindings. Most developers keep Ctrl-based activation for muscle-memory.",
    href: "/shortcuts/",
    linkLabel: "View shortcuts and commands",
    icon: Keyboard,
  },
];

const workflows = [
  {
    title: "Toggle mode for quick dictation",
    description:
      "Use toggle mode when you need short bursts: comments, TODO notes, commit message drafts, or quick variable descriptions.",
    tips: [
      "Double-tap your shortcut to start and stop.",
      "Best for short phrases between normal typing.",
      "Great when context-switching between keyboard and voice.",
    ],
    icon: ToggleLeft,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Push-to-talk for continuous coding (recommended)",
    description:
      "Use push-to-talk when writing longer explanations in docs, code reviews, and comments. Hold key to speak, release to stop.",
    tips: [
      "Keeps accidental transcription low in noisy environments.",
      "Predictable start/stop behavior for focused coding sessions.",
      "Preferred by many developers for precise control.",
    ],
    icon: Mic,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Voice commands for code editing",
    description:
      "Combine dictation with editing commands like punctuation and structure helpers to move faster through repetitive formatting.",
    tips: [
      "Use commands like \"new line\", \"tab\", and \"semicolon\".",
      "Treat voice as an editor assistant, not a full code generator.",
      "Use keyboard for dense syntax-heavy sections.",
    ],
    icon: MessageSquare,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
];

const vscodeTips = [
  "Dictate comments first: inline comments and docstrings are ideal voice targets.",
  "For strings, speak full sentence chunks and then fix quotes/escaping with keyboard.",
  "Use \"new line\" and \"tab\" commands for indentation rhythm in blocks.",
  "When writing markdown in VS Code, voice dictation is often faster than typing.",
];

const troubleshootingTips = [
  "No text appears in VS Code: verify Vocalinux is active and the editor window is focused.",
  "Shortcut conflicts: remap Vocalinux activation to avoid overlapping VS Code keybinds.",
  "Unexpected punctuation: review your voice command phrases and disable commands if needed.",
  "Low accuracy: use a quieter mic setup and test another model size/engine in settings.",
];

export const metadata: Metadata = buildPageMetadata({
  title: "How to Dictate in VS Code on Linux (Voice Coding Workflow)",
  description:
    "Learn how to use voice dictation in VS Code on Linux. Setup Vocalinux for programming, recommended workflows for coding, PTT vs toggle mode, and troubleshooting tips.",
  path: "/voice-typing-vscode",
  keywords: [
    "voice typing VS Code Linux",
    "voice coding linux",
    "dictate code linux",
    "speech to text programming linux",
    "vocalinux VS Code",
  ],
});

export default function VoiceTypingVsCodePage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "How to Dictate in VS Code on Linux (Voice Coding Workflow)",
    description:
      "Learn how to use voice dictation in VS Code on Linux. Setup Vocalinux for programming, recommended workflows for coding, PTT vs toggle mode, and troubleshooting tips.",
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
    mainEntityOfPage: absoluteUrl("/voice-typing-vscode"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Code2 className="h-4 w-4" />
          VS Code Workflow
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          How to Dictate in VS Code on Linux (Voice Coding Workflow)
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Learn how to use Vocalinux for practical, low-friction voice coding in VS Code on Linux.
          This guide covers setup, toggle vs push-to-talk, editing workflows, and common fixes.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-3 flex items-center gap-2 font-display text-2xl font-semibold">
          <Lightbulb className="h-5 w-5 text-primary" />
          Why use voice coding in VS Code?
        </h2>
        <p className="text-muted-foreground">
          Voice dictation helps developers reduce repetitive typing, keep momentum during documentation,
          and lower hand strain. For most workflows, the sweet spot is hybrid: keyboard for syntax,
          voice for comments, explanations, notes, and refactors written in plain language.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Setup in 2 steps</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {setupSteps.map((step) => {
            const Icon = step.icon;
            return (
              <article
                key={step.title}
                className="rounded-[12px] border border-border bg-background p-5"
              >
                <div className="mb-3 inline-flex rounded-lg bg-primary/10 p-2">
                  <Icon className="h-4 w-4 text-primary" />
                </div>
                <h3 className="mb-2 font-semibold">{step.title}</h3>
                <p className="mb-3 text-sm text-muted-foreground">{step.description}</p>
                <Link href={step.href} className="text-sm font-semibold text-primary hover:underline">
                  {step.linkLabel}
                </Link>
              </article>
            );
          })}
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Recommended workflows</h2>
        <div className="space-y-4">
          {workflows.map((workflow) => {
            const Icon = workflow.icon;

            return (
              <article
                key={workflow.title}
                className="rounded-[12px] border border-border bg-background p-5"
              >
                <h3 className="mb-2 flex items-center gap-3 text-lg font-semibold">
                  <span className={`rounded-lg p-2 ${workflow.iconBg}`}>
                    <Icon className={`h-4 w-4 ${workflow.iconColor}`} />
                  </span>
                  {workflow.title}
                </h3>
                <p className="mb-3 text-sm text-muted-foreground">{workflow.description}</p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {workflow.tips.map((tip) => (
                    <li key={tip} className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <span>{tip}</span>
                    </li>
                  ))}
                </ul>
              </article>
            );
          })}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-muted p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">VS Code-specific tips</h2>
        <ul className="space-y-3 text-sm text-muted-foreground">
          {vscodeTips.map((tip) => (
            <li key={tip} className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <span>{tip}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-muted p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold text-muted-foreground">
          <Bug className="h-5 w-5" />
          Troubleshooting
        </h2>
        <ul className="space-y-3 text-sm text-muted-foreground">
          {troubleshootingTips.map((tip) => (
            <li key={tip} className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{tip}</span>
            </li>
          ))}
        </ul>
        <div className="mt-5 flex flex-wrap gap-4 text-sm">
          <Link href="/for-developers/" className="font-semibold text-primary hover:underline">
            Developer guide
          </Link>
          <Link href="/shortcuts/" className="font-semibold text-primary hover:underline">
            Shortcuts and commands
          </Link>
          <Link href="/install/" className="font-semibold text-primary hover:underline">
            Installation docs
          </Link>
        </div>
      </section>

      <section className="rounded-[12px] border border-primary/20 bg-primary/5 p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Ready to voice-type in VS Code?</h2>
        <p className="mb-6 max-w-3xl text-muted-foreground">
          Install Vocalinux and use a hybrid keyboard + voice workflow that fits real-world Linux
          development.
        </p>
        <Link
          href="/install/"
          className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
        >
          Install Vocalinux
          <ChevronRight className="h-4 w-4" />
        </Link>
      </section>
    </SeoSubpageShell>
  );
}
