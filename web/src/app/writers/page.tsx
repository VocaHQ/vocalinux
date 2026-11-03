import Link from "next/link";
import { type Metadata } from "next";
import {
  BookOpen,
  ChevronRight,
  FileText,
  Globe,
  Heart,
  Lock,
  Mic,
  PenLine,
  ToggleLeft,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const writingModes = [
  {
    title: "Toggle mode for natural writing flow",
    description:
      "Use toggle mode for long-form drafting. Start dictation, speak continuously, and stay in creative flow while writing chapters, essays, and long notes.",
    icon: ToggleLeft,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Push-to-talk for structured writing",
    description:
      "Use push-to-talk when precision matters: outlines, headlines, bullet lists, or source notes. Hold to speak, release to review and edit.",
    icon: Mic,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
];

const writingCommands = [
  "new line",
  "new paragraph",
  "period",
  "comma",
  "question mark",
  "colon",
  "quote",
  "delete that",
  "undo",
  "capitalize",
];

const integrations = [
  {
    app: "Obsidian",
    description:
      "Capture ideas directly into your vault, journal entries, or daily notes without breaking thought flow.",
  },
  {
    app: "Notion",
    description:
      "Draft blog outlines, content calendars, and research notes with hands-free voice input.",
  },
  {
    app: "LibreOffice",
    description:
      "Dictate manuscripts, essays, and article drafts in Writer with standard punctuation commands.",
  },
  {
    app: "Terminal Editors",
    description:
      "Use Vocalinux with terminal apps and editors to write notes, commit messages, and drafts quickly.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Voice Dictation for Writers on Linux",
  description:
    "Complete guide to voice dictation for writers on Linux. How to dictate novels, blog posts, and notes using Vocalinux. Hands-free writing workflow tips.",
  path: "/writers",
  keywords: [
    "voice dictation for writers linux",
    "dictate novel linux",
    "voice typing obsidian linux",
    "voice to text writing linux",
    "linux dictation for authors",
  ],
});

export default function WritersPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Voice Dictation for Writers on Linux: Dictate Novels, Articles & Notes",
    description:
      "Complete guide to voice dictation for writers on Linux. How to dictate novels, blog posts, and notes using Vocalinux. Hands-free writing workflow tips.",
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
    mainEntityOfPage: absoluteUrl("/writers"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <PenLine className="h-4 w-4" />
          For Writers
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Voice Dictation for Writers on Linux: Dictate Novels, Articles & Notes
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Write at the speed of thought. Vocalinux helps novelists, bloggers, students, and
          journalists dictate drafts hands-free in their favorite Linux apps.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">Why Writers Should Use Voice Dictation</h2>
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="mb-3 inline-flex items-center gap-2 font-semibold">
              <Heart className="h-5 w-5 text-primary" /> RSI prevention and comfort
            </h3>
            <p className="text-sm text-muted-foreground">
              Long writing sessions can strain wrists and fingers. Dictating reduces repetitive
              keyboard stress and helps you keep creating without pain.
            </p>
          </div>
          <div>
            <h3 className="mb-3 inline-flex items-center gap-2 font-semibold">
              <FileText className="h-5 w-5 text-primary" /> More words, less friction
            </h3>
            <p className="text-sm text-muted-foreground">
              Most people speak faster than they type. Voice dictation helps produce first drafts,
              lecture notes, and article outlines faster while preserving momentum.
            </p>
          </div>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Recommended Workflow for Writers</h2>
        <div className="grid gap-6 md:grid-cols-2">
          {writingModes.map((mode) => {
            const Icon = mode.icon;
            return (
              <article
                key={mode.title}
                className="rounded-[12px] border border-border bg-background p-6"
              >
                <div className={`mb-3 inline-flex rounded-lg p-2.5 ${mode.iconBg}`}>
                  <Icon className={`h-5 w-5 ${mode.iconColor}`} />
                </div>
                <h3 className="mb-2 font-semibold">{mode.title}</h3>
                <p className="text-sm text-muted-foreground">{mode.description}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">Voice Commands Useful for Writing</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          These commands help maintain writing rhythm while dictating punctuation and formatting.
        </p>
        <div className="flex flex-wrap gap-2">
          {writingCommands.map((cmd) => (
            <kbd
              key={cmd}
              className="rounded-lg border border-border bg-muted px-2 py-1 text-xs font-mono"
            >
              "{cmd}"
            </kbd>
          ))}
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">App Integrations for Writing Workflows</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {integrations.map((integration) => (
            <article
              key={integration.app}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 font-semibold">{integration.app}</h3>
              <p className="text-sm text-muted-foreground">{integration.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Link
          href="/languages/"
          className="rounded-[12px] border border-border bg-background p-5 transition-colors hover:bg-muted hover:bg-muted"
        >
          <Globe className="mb-3 h-6 w-6 text-primary" />
          <h3 className="mb-1 font-semibold">Multilingual Writing</h3>
          <p className="text-sm text-muted-foreground">See supported languages for dictation.</p>
        </Link>

        <Link
          href="/rsi-prevention/"
          className="rounded-[12px] border border-border bg-background p-5 transition-colors hover:bg-muted hover:bg-muted"
        >
          <Heart className="mb-3 h-6 w-6 text-primary" />
          <h3 className="mb-1 font-semibold">Health Benefits</h3>
          <p className="text-sm text-muted-foreground">Learn how dictation helps prevent RSI.</p>
        </Link>

        <Link
          href="/offline/"
          className="rounded-[12px] border border-border bg-background p-5 transition-colors hover:bg-muted hover:bg-muted"
        >
          <Lock className="mb-3 h-6 w-6 text-primary" />
          <h3 className="mb-1 font-semibold">Privacy Benefits</h3>
          <p className="text-sm text-muted-foreground">Keep drafts private with offline dictation.</p>
        </Link>

        <Link
          href="/use-cases/"
          className="rounded-[12px] border border-border bg-background p-5 transition-colors hover:bg-muted hover:bg-muted"
        >
          <BookOpen className="mb-3 h-6 w-6 text-primary" />
          <h3 className="mb-1 font-semibold">More Use Cases</h3>
          <p className="text-sm text-muted-foreground">Explore all workflows powered by Vocalinux.</p>
        </Link>
      </section>

      <section className="rounded-[12px] border border-primary/30 bg-primary/10 p-8">
        <h2 className="mb-3 font-display text-2xl font-semibold">Start Writing with Your Voice</h2>
        <p className="mb-6 max-w-3xl text-muted-foreground">
          Install Vocalinux and start dictating novels, blog posts, academic notes, and newsroom
          drafts directly on Linux - without cloud lock-in.
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
