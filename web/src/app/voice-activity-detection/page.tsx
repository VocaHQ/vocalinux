import Link from "next/link";
import { type Metadata } from "next";
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Mic,
  Settings,
  Shield,
  Volume2,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, AUTHOR_PERSON, buildPageMetadata } from "@/lib/seo";

const vadBenefits = [
  {
    title: "Drops silence-only buffers",
    description:
      "Silero VAD helps Vocalinux ignore chunks that do not contain speech before they reach the recognition engine.",
  },
  {
    title: "Cleaner dictation sessions",
    description:
      "Better speech boundaries reduce empty transcriptions and lower the chance that silence becomes stray text.",
  },
  {
    title: "Same sensitivity control",
    description:
      "The existing 1-5 VAD sensitivity setting works for both Silero and the amplitude fallback.",
  },
];

const signalFlow = [
  "Microphone audio is captured locally.",
  "Vocalinux checks each short chunk for speech activity.",
  "Speech chunks are kept for transcription.",
  "Silence-only chunks are dropped before recognition.",
  "If Silero is unavailable, amplitude-based VAD takes over.",
];

export const metadata: Metadata = buildPageMetadata({
  title: "Silero VAD for Cleaner Linux Voice Dictation",
  description:
    "Learn how Vocalinux uses Silero neural voice activity detection to drop silence-only buffers and improve Linux speech-to-text dictation.",
  path: "/voice-activity-detection",
  keywords: [
    "silero vad linux dictation",
    "voice activity detection speech to text",
    "vocalinux vad sensitivity",
    "cleaner whisper dictation linux",
  ],
});

export default function VoiceActivityDetectionPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Silero VAD for Cleaner Linux Voice Dictation",
    description:
      "How Vocalinux uses neural voice activity detection to separate speech from silence before transcription.",
    dateModified: "2026-06-11",
    author: AUTHOR_PERSON,
    publisher: {
      "@type": "Organization",
      name: "Vocalinux",
      logo: {
        "@type": "ImageObject",
        url: absoluteUrl("/vocalinux.png"),
      },
    },
    mainEntityOfPage: absoluteUrl("/voice-activity-detection"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="border-primary/30 bg-primary/10 mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium text-primary">
          <Activity className="h-4 w-4" />
          v0.12.0 Silero VAD
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Silero VAD for Cleaner Linux Voice Dictation
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux now uses Silero neural voice activity detection when ONNX
          Runtime support is available. It identifies speech before
          transcription, drops silence-only buffers, and falls back safely when
          the neural backend is not installed.
        </p>
      </section>

      <section className="mb-12 grid gap-6 md:grid-cols-3">
        {vadBenefits.map((benefit) => (
          <article
            key={benefit.title}
            className="rounded-[12px] border border-border bg-background p-6"
          >
            <span className="mb-4 inline-flex rounded-[12px] bg-primary/10 p-3">
              <CheckCircle2 className="h-6 w-6 text-primary" />
            </span>
            <h2 className="mb-2 text-xl font-semibold">{benefit.title}</h2>
            <p className="text-sm text-muted-foreground">
              {benefit.description}
            </p>
          </article>
        ))}
      </section>

      <section className="mb-12 grid gap-6 lg:grid-cols-[1.05fr_1fr]">
        <div className="rounded-[12px] border border-border bg-muted p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <Volume2 className="h-5 w-5 text-primary" />
            How Speech Detection Fits In
          </h2>
          <ol className="space-y-3 text-sm text-muted-foreground">
            {signalFlow.map((step, index) => (
              <li key={step} className="flex gap-3">
                <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <Settings className="h-5 w-5 text-primary" />
            Settings and Installation
          </h2>
          <div className="space-y-4 text-sm text-muted-foreground">
            <p>
              The official installer attempts to install neural VAD support. If
              ONNX Runtime is not available, Vocalinux logs the fallback and
              continues with amplitude-based VAD.
            </p>
            <div className="rounded-lg bg-[color:var(--terminal)] p-4">
              <code className="text-[color:var(--terminal-fg)]">
                pip install &quot;vocalinux[vad]&quot;
              </code>
            </div>
            <p>
              The Recognition tab shows which backend is active. Higher VAD
              sensitivity values are more responsive to quiet speech for both
              backends.
            </p>
          </div>
        </div>
      </section>

      <section className="mb-12 grid gap-6 md:grid-cols-3">
        {[
          {
            icon: Shield,
            title: "Local by design",
            description:
              "Silero runs on your machine. Voice activity detection does not require a cloud service.",
          },
          {
            icon: Cpu,
            title: "Small CPU-side helper",
            description:
              "The VAD step is a lightweight pre-filter before whisper.cpp, Whisper, VOSK, or Remote API recognition.",
          },
          {
            icon: Mic,
            title: "Useful for push-to-talk",
            description:
              "Cleaner speech boundaries also help short recordings and stop-on-release flows avoid silence-only output.",
          },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <article
              key={item.title}
              className="rounded-[12px] border border-border bg-background p-6"
            >
              <span className="bg-primary/10 mb-4 inline-flex rounded-[12px] p-3">
                <Icon className="h-6 w-6 text-primary" />
              </span>
              <h2 className="mb-2 text-xl font-semibold">{item.title}</h2>
              <p className="text-sm text-muted-foreground">
                {item.description}
              </p>
            </article>
          );
        })}
      </section>

      <section className="border-primary/20 bg-primary/5 rounded-[12px] border p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Related Guides</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Link href="/shortcuts/" className="group">
            <h3 className="font-semibold">Shortcut modes</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Pair VAD with toggle or push-to-talk activation.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              View shortcuts <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/advanced-settings/" className="group">
            <h3 className="font-semibold">Advanced recognition tuning</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Adjust whisper.cpp thresholds and anti-hallucination controls.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Tune settings <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/compare/" className="group">
            <h3 className="font-semibold">Engine comparison</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              See how VAD works before local and remote recognition engines.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Compare engines <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
