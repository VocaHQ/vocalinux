import Link from "next/link";
import { type Metadata } from "next";
import {
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Code,
  Terminal,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { TerminalBlock } from "@/components/terminal-block";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/custom-dictionary";

const dictionaryFileCommand =
  "vocalinux --dictionary-file /path/to/dictionary.txt";

const howToSteps = [
  {
    name: "Open the Custom Dictionary page",
    text: "Open Settings from the tray menu and choose Custom Dictionary in the sidebar.",
  },
  {
    name: "Add custom terms",
    text: "Switch on Use custom terms, type a name or term into the Add a term field and click Add term. Or point Terms file at an existing UTF-8 file.",
  },
  {
    name: "Add transcript corrections",
    text: "Under Transcript corrections, enter what the engine writes (for example super base) and what you want instead (for example Supabase), then click Add correction.",
  },
  {
    name: "Optionally set a post-processing script",
    text: "Open the Post-Processing page, enter the path to an executable script in Script Path or click Browse…, and leave the field empty to turn it off.",
  },
  {
    name: "Dictate",
    text: "Both dictionary files are re-read before each completed segment, so changes apply to your next dictation without a restart.",
  },
];

const pipeline = [
  "The engine transcribes your speech, biased by custom terms on Whisper, whisper.cpp and Faster Whisper.",
  "Transcript corrections replace known mishearings. This works with every engine.",
  "Voice commands are interpreted, if Voice Commands is on.",
  "The post-processing script, if set, rewrites the final text.",
  "The result is typed into the focused app, or appended to the Dictation Pad.",
];

const faqs = [
  {
    q: "Which engines use custom terms?",
    a: "Vocabulary bias works with Whisper, whisper.cpp and Faster Whisper. Transcript corrections work with every engine, including VOSK, Parakeet and the Remote API.",
  },
  {
    q: "Are corrections added to the vocabulary bias automatically?",
    a: "No. Corrections and terms are separate. If you want the engine to lean toward a spelling as well as fix it afterwards, add it as a term too.",
  },
  {
    q: "My correction triggered a voice command. Why?",
    a: "Corrections run before voice commands. If a replacement is itself a command phrase, it will act as one. Choose replacement text that is not a voice command unless that is what you want.",
  },
  {
    q: "My post-processing script runs but nothing changes. What should I check?",
    a: "Vocalinux falls back to the original text when the script exits non-zero, cannot be started, or runs longer than 10 seconds. Make sure the file is executable, the path is absolute, and the script writes to standard output. The Vocalinux log records the exit code and standard error.",
  },
  {
    q: "Why did a segment disappear after I added a script?",
    a: "If the script exits successfully but prints nothing, Vocalinux types nothing for that segment. Make sure every code path writes the text back out.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Custom Dictionary, Corrections and Post-Processing | Vocalinux",
  description:
    "Teach Vocalinux your jargon: custom terms that bias Whisper, transcript corrections for every engine, and a stdin/stdout post-processing script hook.",
  path: PAGE_PATH,
  keywords: [
    "custom dictionary voice dictation Linux",
    "Whisper custom vocabulary",
    "whisper.cpp initial prompt terms",
    "speech to text corrections",
    "dictation post-processing script",
    "Vocalinux custom dictionary",
  ],
});

export default function CustomDictionaryPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline:
      "Custom Dictionary, Transcript Corrections and Post-Processing in Vocalinux",
    description:
      "How Vocalinux custom terms, transcript corrections and the post-processing script hook work, with exact file formats and safe example scripts.",
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
    name: "Set up a custom dictionary in Vocalinux",
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
          Custom dictionary, corrections and post-processing
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Speech models stumble on product names, colleagues&apos; names and
          project jargon. Vocalinux gives you three tools for that: custom terms
          that steer Whisper-family engines toward your vocabulary, transcript
          corrections that fix known mishearings on every engine, and a script
          hook that can rewrite each result before it is typed.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-3">
        <div className="rounded-[12px] border border-border bg-background p-5">
          <BookOpen className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Custom terms</h3>
          <p className="text-sm text-muted-foreground">
            A plain text list, one term per line, passed to the engine as
            context so it is more likely to spell those words your way.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <CheckCircle2
            className="mb-3 h-6 w-6 text-primary"
            aria-hidden="true"
          />
          <h3 className="mb-2 font-semibold">Transcript corrections</h3>
          <p className="text-sm text-muted-foreground">
            Heard-as and replace-with pairs applied to every finished
            transcript, whatever the engine.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Code className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Post-processing script</h3>
          <p className="text-sm text-muted-foreground">
            Any executable that reads text on stdin and writes the replacement
            on stdout.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">Set it up</h2>
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
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Order of operations
        </h2>
        <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
          {pipeline.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
        <p className="mt-4 text-sm text-muted-foreground">
          Because corrections come before voice commands, a correction can stop
          a mishearing from triggering a destructive command. The flip side:
          avoid replacements that are themselves command phrases. The command
          list is on the <Link href="/shortcuts/">voice commands page</Link>.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Custom terms file
        </h2>
        <p className="mb-4 text-muted-foreground">
          Terms live in <code>~/.config/vocalinux/dictionary.txt</code> by
          default: UTF-8, one term per line. Blank lines and lines starting with{" "}
          <code>#</code> are skipped, and duplicates are ignored regardless of
          case. The plain line format is deliberate, so accessibility tools and
          scripts can maintain the same file.
        </p>
        <pre className="subpage-terminal mb-4 overflow-x-auto p-4">
          <code>{`# ~/.config/vocalinux/dictionary.txt
Supabase
Kubernetes
PipeWire
Okonkwo`}</code>
        </pre>
        <h3 className="mb-2 font-semibold">Limits and engine support</h3>
        <ul className="mb-4 list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            Bias applies to Whisper, whisper.cpp and Faster Whisper. On
            whisper.cpp the terms are appended after anything in Advanced →
            Initial Prompt, so your own prompt is kept.
          </li>
          <li>
            Up to 200 terms are used by default (
            <code>dictionary.max_words</code> in config.json), and the combined
            prompt stops at 2,000 characters.
          </li>
          <li>
            The editor rejects a single term longer than 200 characters. A file
            larger than 1 MiB is read only up to its last complete line inside
            that limit.
          </li>
        </ul>
        <h3 className="mb-2 font-semibold">Session-only terms file</h3>
        <p className="mb-3 text-muted-foreground">
          To try a different list without touching saved settings, start
          Vocalinux with:
        </p>
        <TerminalBlock
          command={dictionaryFileCommand}
          displayCommand={dictionaryFileCommand}
          label="terminal"
        />
        <p className="mt-3 text-sm text-muted-foreground">
          The custom terms controls are disabled for that session. Transcript
          corrections still apply.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Transcript corrections file
        </h2>
        <p className="mb-4 text-muted-foreground">
          Corrections are stored separately in{" "}
          <code>~/.config/vocalinux/custom-dictionary-corrections.json</code>,
          always in the config directory, whatever terms file you use. The
          format is versioned:
        </p>
        <pre className="subpage-terminal mb-4 overflow-x-auto p-4">
          <code>{`{
  "version": 1,
  "corrections": [
    { "heard": "super base", "replacement": "Supabase" },
    { "heard": "pipe wire", "replacement": "PipeWire" }
  ]
}`}</code>
        </pre>
        <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            <code>heard</code> matches case-insensitively, only as a whole word
            or phrase.
          </li>
          <li>
            <code>replacement</code> is inserted with exactly the spelling you
            typed.
          </li>
          <li>
            Longer phrases win over shorter ones. For a repeated heard phrase,
            the first wins.
          </li>
          <li>Up to 500 corrections, each side up to 500 characters.</li>
          <li>
            Settings refuses to edit a hand-written file with extra fields or
            entries it would have to change. Fix the JSON, or edit it only by
            hand.
          </li>
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <Terminal className="h-5 w-5 text-primary" aria-hidden="true" />
          The post-processing script hook
        </h2>
        <p className="mb-4 text-muted-foreground">
          The path is saved as <code>post_processing.script_path</code> (empty
          means off). For each completed segment, Vocalinux runs the file like
          this:
        </p>
        <div className="mb-4 overflow-x-auto rounded-[12px] border border-border bg-background p-6">
          <table className="w-full text-left text-sm">
            <tbody>
              {[
                [
                  "Invocation",
                  "The path is executed directly, with no arguments and no shell. Use an absolute path to an executable file; ~ is not expanded.",
                ],
                [
                  "stdin",
                  "The text of one segment, after corrections and voice commands.",
                ],
                [
                  "stdout",
                  "The replacement text, used verbatim. One trailing newline is dropped if the input had none, so echo and print are safe; other newlines are kept.",
                ],
                [
                  "Environment",
                  "Inherits Vocalinux's environment. When Vocalinux runs from the AppImage, the bundle's library paths are removed first.",
                ],
                ["Timeout", "10 seconds."],
                [
                  "Failure",
                  "A non-zero exit, a timeout or a script that cannot start means the original text is used. Standard error is logged on a non-zero exit.",
                ],
                ["Empty output", "Nothing is typed for that segment."],
                [
                  "Ordering",
                  "Scripts run one at a time on a dedicated worker, in order, so a slow script does not interrupt dictation. A waiting segment is dropped if you switch to another app before it is typed, unless it is going to the Dictation Pad.",
                ],
              ].map(([label, value]) => (
                <tr key={label} className="border-b border-border">
                  <th scope="row" className="py-3 pr-4 align-top font-semibold">
                    {label}
                  </th>
                  <td className="py-3 text-muted-foreground">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 font-semibold">Example: uppercase everything</h3>
        <p className="mb-3 text-sm text-muted-foreground">
          The example from the Vocalinux user guide. Make it executable with{" "}
          <code>chmod +x</code> before setting the path.
        </p>
        <pre className="subpage-terminal mb-4 overflow-x-auto p-4">
          <code>{`#!/bin/bash
tr '[:lower:]' '[:upper:]'`}</code>
        </pre>
        <h3 className="mb-2 font-semibold">
          Example: typographic apostrophes in Python
        </h3>
        <p className="mb-3 text-sm text-muted-foreground">
          Reads everything from stdin and writes it back without adding a
          newline. Any exception exits non-zero, so Vocalinux falls back to the
          original text.
        </p>
        <pre className="subpage-terminal mb-4 overflow-x-auto p-4">
          <code>{`#!/usr/bin/env python3
import sys

text = sys.stdin.read()
sys.stdout.write(text.replace("'", "\\u2019"))`}</code>
        </pre>
        <p className="text-sm text-muted-foreground">
          Before pointing Vocalinux at a script, pipe a sample sentence into it
          from a terminal and check that it prints the text back. Output is not
          written to the log, but anything your script does with the text
          (files, network calls) is up to the script.
        </p>
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
          Make dictation speak your language
        </h2>
        <p className="mb-6 text-muted-foreground">
          Custom terms help most with a Whisper-family engine; the{" "}
          <Link href="/compare/">engine comparison</Link> and{" "}
          <Link href="/advanced-settings/">advanced settings</Link> pages cover
          the rest of the tuning. Developers may also like{" "}
          <Link href="/for-developers/">dictation for code</Link>.
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
            href="/multilingual-dictation/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Multilingual dictation
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
