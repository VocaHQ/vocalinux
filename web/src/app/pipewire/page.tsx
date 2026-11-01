import Link from "next/link";
import { type Metadata } from "next";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ChevronRight,
  Headphones,
  Mic,
  Volume2,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { TerminalBlock } from "@/components/terminal-block";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/pipewire";
const PAGE_TITLE = "PipeWire Audio Capture for Linux Voice Dictation";
const PAGE_DESCRIPTION =
  "How Vocalinux records from microphones and PipeWire system-audio sources, how it differs from PortAudio, and how to fix wrong-mic, silence and Bluetooth issues.";

const captureRows = [
  {
    path: "Microphones (PortAudio)",
    lists:
      "Input-capable ALSA and PulseAudio devices that PortAudio enumerates, plus System Default",
    records: "A PortAudio stream, downmixed to mono for the speech engine",
    use: "Normal dictation into a mic or headset",
  },
  {
    path: "System audio (PipeWire)",
    lists:
      "Every PipeWire Audio/Sink node, physical or virtual, shown as “System audio: …”",
    records: "pw-record on that sink's monitor, raw 16-bit mono at 16 kHz",
    use: "Transcribing what is playing through an output device",
  },
];

const steps = [
  {
    name: "Open the Audio page",
    text: "Open Vocalinux Settings, go to Audio and find Input Device. Use the refresh button next to the list after plugging in a headset.",
  },
  {
    name: "Pick a source",
    text: "Choose System Default to follow your desktop sound settings, a named microphone to pin that device, or a System audio entry to record what plays through that output.",
  },
  {
    name: "Run the Microphone Test",
    text: "Click Test next to Microphone Test. It records 2 seconds and the level meter shows whether any signal arrived.",
  },
  {
    name: "Try a real dictation",
    text: "Use Test Dictation in the Settings sidebar footer, or your dictation shortcut, to confirm the engine hears speech from the chosen source.",
  },
];

const faqs = [
  {
    question: "Does Vocalinux record microphones through PipeWire?",
    answer:
      "Microphones are listed and opened through PortAudio, including System Default. The native PipeWire path, pw-dump plus pw-record, is used for the System audio entries, because PortAudio cannot reach a sink monitor.",
  },
  {
    question: "Can I capture audio from one application only?",
    answer:
      "No. A System audio entry records the monitor of a whole output device, so everything playing through that sink is mixed into the recording. Per-application stream capture is out of scope in the current code.",
  },
  {
    question: "Why are there no System audio entries in my device list?",
    answer:
      "Vocalinux lists them only when both pw-dump and pw-record are on the PATH and the PipeWire daemon answers. If either tool is missing, the list shows microphones only and nothing else changes.",
  },
  {
    question: "Does system-audio capture send anything online?",
    answer:
      "Not with a local engine. Audio from either path goes to the engine you selected, and local engines run on your machine. If you switch to the Remote API engine or a VocaGateway, audio is sent to the endpoint you configured.",
  },
  {
    question: "Which version added PipeWire capture?",
    answer:
      "PipeWire system-audio capture was added in v0.18.0. Check your version with vocalinux --version.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: `${PAGE_TITLE} | Vocalinux`,
  description: PAGE_DESCRIPTION,
  path: PAGE_PATH,
  keywords: [
    "pipewire voice dictation linux",
    "pipewire speech to text",
    "linux dictation system audio",
    "pw-record transcription",
    "portaudio vs pipewire",
    "vocalinux microphone not working",
    "bluetooth headset dictation linux",
  ],
});

function InlineCode({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground">
      {children}
    </code>
  );
}

export default function PipeWirePage() {
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
        name: "Choose an audio source for Vocalinux dictation",
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
          PipeWire audio capture in Vocalinux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux records from two kinds of source: microphones, opened
          through PortAudio, and system-audio sources that come straight from
          PipeWire. This page explains what each one is for, how to pick the
          right source, and what to check when dictation hears the wrong device
          or nothing at all.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Two capture paths: PortAudio and PipeWire
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          PortAudio enumerates ALSA and PulseAudio devices, not PipeWire nodes.
          That works well for microphones, but it cannot see a sink&apos;s
          monitor, the stream of everything playing through an output. Since
          v0.18.0 Vocalinux asks PipeWire directly: it lists sinks with{" "}
          <InlineCode>pw-dump</InlineCode> and records the chosen one with{" "}
          <InlineCode>pw-record --raw</InlineCode>. PipeWire converts the audio
          to the format Vocalinux asks for inside its own graph, so no format
          negotiation is needed.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Path
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  What it lists
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  How it records
                </th>
                <th scope="col" className="pb-3 font-semibold">
                  Use it for
                </th>
              </tr>
            </thead>
            <tbody>
              {captureRows.map((row) => (
                <tr key={row.path} className="border-b border-border align-top">
                  <th scope="row" className="py-3 pr-4 font-medium">
                    {row.path}
                  </th>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.lists}
                  </td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.records}
                  </td>
                  <td className="py-3 text-muted-foreground">{row.use}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 mt-6 font-semibold">Who this is for</h3>
        <p className="text-sm text-muted-foreground">
          Most people dictate into a microphone and never need to change
          anything. System audio is for the cases a microphone cannot cover
          well, such as transcribing speech from a video or a call that plays
          through your speakers or headphones. For recorded files, the{" "}
          <Link
            href="/transcribe-audio-files/"
            className="text-primary underline"
          >
            file transcription mode
          </Link>{" "}
          is usually the better tool.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          How to choose a source
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
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <div className="rounded-[12px] border border-border bg-background p-5">
            <Mic className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
            <h3 className="mb-2 font-semibold">System Default</h3>
            <p className="text-sm text-muted-foreground">
              Leaves valid default and virtual inputs under the sound
              server&apos;s control, so the mic you pick in desktop sound
              settings is the one Vocalinux hears.
            </p>
          </div>
          <div className="rounded-[12px] border border-border bg-background p-5">
            <Headphones
              className="mb-3 h-6 w-6 text-primary"
              aria-hidden="true"
            />
            <h3 className="mb-2 font-semibold">A named microphone</h3>
            <p className="text-sm text-muted-foreground">
              A valid explicit choice always wins over System Default. Vocalinux
              saves the device name and matches it again by name when indexes
              shift after a replug.
            </p>
          </div>
          <div className="rounded-[12px] border border-border bg-background p-5">
            <Volume2 className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
            <h3 className="mb-2 font-semibold">System audio: …</h3>
            <p className="text-sm text-muted-foreground">
              Records one output device&apos;s monitor. Two sinks with the same
              description get the PipeWire node name added in brackets so you
              can tell them apart.
            </p>
          </div>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Settings and limits
        </h2>
        <h3 className="mb-2 font-semibold">Where the choice is stored</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          The selection lives in{" "}
          <InlineCode>~/.config/vocalinux/config.json</InlineCode> under{" "}
          <InlineCode>audio.device_index</InlineCode> and{" "}
          <InlineCode>audio.device_name</InlineCode>. A{" "}
          <InlineCode>null</InlineCode> index means System Default.
        </p>
        <h3 className="mb-2 font-semibold">Gotchas</h3>
        <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            System audio needs both <InlineCode>pw-dump</InlineCode> and{" "}
            <InlineCode>pw-record</InlineCode>. Without them the entries are
            simply not listed.
          </li>
          <li>
            If a saved System audio sink disappears, Vocalinux refuses to record
            instead of quietly switching to a microphone, because that would
            capture the wrong audio. Pick a source again.
          </li>
          <li>
            A sink monitor records the full mix for that output, including
            notification sounds and any other app playing at the time.
          </li>
          <li>
            The Flatpak release notes list PipeWire system-audio capture as a
            native-install path. Inside the Snap, Settings → Audio lists the
            sound server&apos;s microphones through{" "}
            <InlineCode>pactl</InlineCode> instead.
          </li>
        </ul>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <AlertTriangle className="h-5 w-5 text-primary" aria-hidden="true" />
          Troubleshooting
        </h2>
        <h3 className="mb-2 font-semibold">
          Dictation uses the wrong microphone
        </h3>
        <p className="mb-3 text-sm text-muted-foreground">
          Select the mic by name in Settings → Audio → Input Device rather than
          relying on System Default. On ALSA-only setups where PortAudio
          substitutes some other hardware for the default input, Vocalinux
          prefers an input-capable <InlineCode>pulse</InlineCode> device so it
          follows your desktop&apos;s choice, and logs a warning when none
          exists. Run with debug logging to see which device was opened:
        </p>
        <div className="mb-6">
          <TerminalBlock
            command="vocalinux --debug"
            displayCommand="vocalinux --debug"
          />
        </div>
        <h3 className="mb-2 font-semibold">
          Silence, or a Microphone Stalled notification
        </h3>
        <p className="mb-3 text-sm text-muted-foreground">
          Check mute state and levels in your system sound settings, then list
          capture hardware:
        </p>
        <div className="mb-3">
          <TerminalBlock command="arecord -l" displayCommand="arecord -l" />
        </div>
        <p className="mb-6 text-sm text-muted-foreground">
          A Microphone Stalled notification means the selected input stopped
          delivering audio and Vocalinux stopped that attempt. Use Microphone
          Test, or choose another Input Device. If a stale device index is the
          problem, quit Vocalinux and set{" "}
          <InlineCode>audio.device_index</InlineCode> to{" "}
          <InlineCode>null</InlineCode> in <InlineCode>config.json</InlineCode>.
          With a System audio source, remember that a silent output produces
          silence: start the playback first.
        </p>
        <h3 className="mb-2 font-semibold">Bluetooth headsets</h3>
        <p className="text-sm text-muted-foreground">
          Bluetooth headset microphones use a separate capture profile that is
          sensitive to repeated opening. Vocalinux opens the stream once per
          session and pauses briefly between failed attempts on Bluetooth
          devices. If capture still fails, try a wired microphone to check
          whether the Bluetooth capture path is the cause.
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
          More fixes on the{" "}
          <Link href="/troubleshooting/" className="text-primary underline">
            troubleshooting page
          </Link>
          . How audio is handled with local and remote engines is covered in{" "}
          <Link href="/offline/" className="text-primary underline">
            offline dictation
          </Link>{" "}
          and{" "}
          <Link href="/remote-api/" className="text-primary underline">
            Remote API
          </Link>
          . Speech detection itself is explained in{" "}
          <Link
            href="/voice-activity-detection/"
            className="text-primary underline"
          >
            voice activity detection
          </Link>
          .
        </p>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Pick a source and dictate
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux, choose your microphone or a system-audio source in
          Settings → Audio, and run the Microphone Test before your first
          dictation.
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
            href="/troubleshooting/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Troubleshooting guide
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
