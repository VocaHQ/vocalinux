import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Lock,
  Mic,
  Terminal,
  Users,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { TerminalBlock } from "@/components/terminal-block";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/transcribe-audio-files";

const cliCommand = "vocalinux --transcribe-file meeting.wav";

const howToSteps = [
  {
    name: "Open the tray entry",
    text: "Click the Vocalinux tray icon and choose Transcribe Audio File…",
  },
  {
    name: "Pick a recording",
    text: "Select a WAV file, or an MP3, OGG, FLAC, M4A or Opus file if ffmpeg is installed, and click Open.",
  },
  {
    name: "Download TinyDiarize once",
    text: "The first time, Vocalinux asks to download the TinyDiarize model (about 465 MB, one time). Click Download. It is only used for file transcription and never becomes your dictation model.",
  },
  {
    name: "Wait for the transcript",
    text: "A notification says the file is being transcribed. Long files can take a while. When it finishes, a Transcript window opens with timestamps and speaker labels.",
  },
  {
    name: "Copy or save it",
    text: "Use Copy to put the full transcript on the clipboard, or Save As to write it to a text file (transcript.txt by default).",
  },
];

const formatRows = [
  {
    input: "WAV, 16-bit, 16 kHz, mono or stereo",
    path: "Read directly. No extra tools needed.",
  },
  {
    input: "Any other WAV",
    path: "Decoded with ffmpeg to mono 16 kHz first.",
  },
  {
    input: "MP3, OGG, FLAC, M4A, Opus",
    path: "Offered in the tray file picker when ffmpeg is installed. Decoded with ffmpeg.",
  },
  {
    input: "Other files (CLI)",
    path: "Handed to ffmpeg, so anything your ffmpeg build can decode.",
  },
];

const faqs = [
  {
    q: "Can it label speakers in languages other than English?",
    a: "No. The TinyDiarize model Vocalinux uses, small.en-tdrz, is English-only. Speaker labels and the transcript itself are for English audio.",
  },
  {
    q: "Does Speaker 1 always mean the same person?",
    a: "No. TinyDiarize marks the points where the speaker changes, and Vocalinux numbers each new turn in order. A person who speaks again later gets a new number, so treat the labels as turn markers and rename them yourself.",
  },
  {
    q: "Why does the CLI say the model is not downloaded?",
    a: "vocalinux --transcribe-file never downloads anything. Run Transcribe Audio File… from the tray once and accept the TinyDiarize download, then the CLI can use the model.",
  },
  {
    q: "Is my audio uploaded anywhere?",
    a: "No. The file is decoded and transcribed on your machine with whisper.cpp, even if your dictation engine is set to a remote API. The only network use is the one-time model download.",
  },
  {
    q: "Why can I only pick WAV files in the tray?",
    a: "ffmpeg is not installed or not on your PATH. Without it, the file picker only offers WAV. Install ffmpeg from your distribution's packages to enable MP3, OGG, FLAC, M4A and Opus.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Transcribe Audio Files on Linux Offline with Speakers | Vocalinux",
  description:
    "Transcribe an audio file on Linux offline with Vocalinux: tray or --transcribe-file, local TinyDiarize speaker labels (English), formats, output and limits.",
  path: PAGE_PATH,
  keywords: [
    "transcribe audio file Linux offline",
    "speaker diarization Linux",
    "TinyDiarize",
    "offline meeting transcription Linux",
    "whisper.cpp speaker labels",
    "transcribe WAV MP3 Linux",
  ],
});

export default function TranscribeAudioFilesPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Transcribe Audio Files on Linux Offline with Speaker Labels",
    description:
      "How to transcribe recordings locally with Vocalinux from the tray or the --transcribe-file CLI, and how TinyDiarize speaker labels work.",
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
    name: "Transcribe an audio file with speaker labels in Vocalinux",
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
          Transcribe audio files offline, with speaker labels
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux can turn a recorded meeting, interview or voice memo into a
          text transcript on your own machine. It uses TinyDiarize, a
          whisper.cpp model that also marks where the speaker changes, so the
          transcript comes out as timestamped blocks labelled Speaker 1, Speaker
          2 and so on. Start it from the tray or from a terminal.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-3">
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Mic className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">
            For recordings, not live dictation
          </h3>
          <p className="text-sm text-muted-foreground">
            File transcription is separate from the dictation pipeline. It never
            types into other apps and does not change your dictation model.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Users className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Speaker turns, English only</h3>
          <p className="text-sm text-muted-foreground">
            The model is <code>small.en-tdrz</code>. It is English-only, so use
            it for English recordings.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Lock className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Local processing</h3>
          <p className="text-sm text-muted-foreground">
            Audio is decoded and transcribed on your computer. Nothing is sent
            to a server.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          From the tray
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
          The model download is checked against a pinned SHA-256 digest before
          use, like every other Vocalinux model. The status line under the
          transcript reports how many blocks were found and the highest speaker
          number.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <Terminal className="h-5 w-5 text-primary" aria-hidden="true" />
          From the command line
        </h2>
        <p className="mb-4 text-muted-foreground">
          <code>--transcribe-file PATH</code> transcribes one file, prints the
          diarized transcript to standard output and exits:
        </p>
        <TerminalBlock
          command={cliCommand}
          displayCommand={cliCommand}
          label="terminal"
        />
        <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
          <li>
            It needs no display and no tray, and it runs alongside a Vocalinux
            instance that is already running, so it works over SSH or from a
            script.
          </li>
          <li>
            It does not download the model. Fetch TinyDiarize once through the
            tray entry first, otherwise the command stops with a message saying
            the model is not downloaded yet.
          </li>
          <li>
            Because the transcript goes to standard output, you can redirect it
            to a file with your shell. Errors go to standard error, prefixed
            with <code>vocalinux: could not transcribe</code>, and the exit
            status is 1. A file with no detectable speech prints{" "}
            <code>vocalinux: no speech detected</code>.
          </li>
        </ul>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Supported input formats
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Input</th>
                <th className="pb-3 font-semibold">How Vocalinux reads it</th>
              </tr>
            </thead>
            <tbody>
              {formatRows.map((row) => (
                <tr key={row.input} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{row.input}</td>
                  <td className="py-3 text-muted-foreground">{row.path}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Vocalinux does not install ffmpeg for you. Without it, only 16-bit 16
          kHz WAV files can be transcribed, and the tray picker&apos;s filter
          says so.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Output format
        </h2>
        <p className="mb-4 text-muted-foreground">
          Each block is one speaker turn: a <code>[HH:MM:SS]</code> timestamp
          for where it starts, the speaker label, then the text. Blocks are
          separated by a blank line. The Transcript window, Copy, Save As and
          the CLI all use the same layout. The lines below show the shape only;
          they are not real output.
        </p>
        <pre className="subpage-terminal overflow-x-auto p-4">
          <code>{`[00:00:00] Speaker 1: <first turn>

[00:00:14] Speaker 2: <second turn>

[00:00:31] Speaker 3: <third turn>`}</code>
        </pre>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          How speaker labels work
        </h2>
        <p className="mb-4 text-muted-foreground">
          TinyDiarize is a small, English-only whisper.cpp model whose output
          includes a speaker-turn marker wherever it detects a change of voice.
          Vocalinux runs it in whisper.cpp&apos;s tinydiarize mode and splits
          the text at each marker. Each new block gets the next number.
        </p>
        <p className="text-muted-foreground">
          That makes the labels positional, not identities. In a two-person
          interview the transcript reads Speaker 1, Speaker 2, Speaker 3,
          Speaker 4 as the two people take turns, rather than alternating
          between 1 and 2. Turn boundaries are useful for reading and editing;
          assigning names is up to you.
        </p>
      </section>

      <section className="bg-primary/5 mb-12 rounded-[12px] border border-border p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Privacy and limitations
        </h2>
        <ul className="space-y-3 text-sm text-muted-foreground">
          {[
            "Local: ffmpeg decoding and whisper.cpp transcription both run on your machine. File transcription always uses the local TinyDiarize model, even when dictation is set to the Remote API engine.",
            "Network: only the one-time model download, from a pinned upstream revision.",
            "Storage: the transcript is not written to disk unless you click Save As or redirect the CLI output.",
            "English only, and speaker numbers do not identify people.",
            "The model is about 465 MB, so the first run needs that much free disk space plus download time.",
            "Long files take a while. The tray shows a notification while it works.",
          ].map((item) => (
            <li key={item} className="flex items-start gap-2">
              <CheckCircle2
                className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary"
                aria-hidden="true"
              />
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-muted-foreground">
          More on what stays on your machine:{" "}
          <Link href="/offline/">offline dictation</Link> and the{" "}
          <Link href="/privacy/">privacy policy</Link>.
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
          Transcribe your first file
        </h2>
        <p className="mb-6 text-muted-foreground">
          File transcription is available from v0.18.0; check yours with{" "}
          <code>vocalinux --version</code>. For live dictation model choices,
          see the <Link href="/whisper-model-guide/">Whisper model guide</Link>;
          to fix names the model mishears in dictation, use the{" "}
          <Link href="/custom-dictionary/">custom dictionary</Link>.
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
            href="/dictation-pad/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Dictation Pad
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
