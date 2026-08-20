import Link from "next/link";
import { type Metadata } from "next";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Globe,
  Lock,
  Network,
  Server,
  Settings,
  Terminal,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const protocolOptions = [
  {
    name: "OpenAI-compatible",
    endpoint: "/v1/audio/transcriptions",
    description:
      "Use servers that expose the common Whisper transcription API shape, including Speaches, LocalAI, and other compatible backends.",
  },
  {
    name: "whisper.cpp server",
    endpoint: "/inference",
    description:
      "Point Vocalinux at the HTTP server bundled with whisper.cpp when you want a small LAN transcription appliance.",
  },
];

const workflowSteps = [
  "Vocalinux records microphone audio locally as 16 kHz mono PCM.",
  "Voice activity detection decides when an utterance is ready.",
  "The utterance is packaged as an in-memory WAV upload.",
  "The configured server returns JSON with a text field.",
  "Vocalinux injects the transcription into the focused Linux app.",
];

const setupSteps = [
  {
    title: "Run a trusted transcription server",
    description:
      "Start a whisper.cpp server or an OpenAI-compatible Whisper service on a machine your Linux desktop can reach.",
  },
  {
    title: "Open Settings -> Advanced",
    description:
      "Remote API is a power-user engine. Enable advanced settings, then configure the Remote Server section.",
  },
  {
    title: "Choose the endpoint format",
    description:
      "Select OpenAI-compatible or whisper.cpp so Vocalinux sends the multipart fields your server expects.",
  },
  {
    title: "Test, then dictate",
    description:
      "Use the connection test as a reachability check, then start dictating with the same shortcut flow as local engines.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Remote API Speech Recognition for Linux Dictation",
  description:
    "Configure Vocalinux Remote API speech recognition with OpenAI-compatible Whisper servers or whisper.cpp server endpoints for Linux voice dictation.",
  path: "/remote-api",
  keywords: [
    "remote api speech recognition linux",
    "openai compatible whisper linux dictation",
    "whisper.cpp server vocalinux",
    "self hosted transcription linux",
  ],
});

export default function RemoteApiPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Remote API Speech Recognition for Linux Dictation",
    description:
      "How Vocalinux connects Linux voice dictation to OpenAI-compatible and whisper.cpp remote transcription servers.",
    dateModified: "2026-06-11",
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
    mainEntityOfPage: absoluteUrl("/remote-api"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="border-primary/30 bg-primary/10 mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium text-primary">
          <Server className="h-4 w-4" />
          v0.12.0 Remote Engine
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Remote API Speech Recognition for Linux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux can offload the heavy transcription step to a trusted HTTP
          server while keeping desktop capture, voice activity detection,
          shortcut handling, and text injection on your Linux machine.
        </p>
      </section>

      <section className="mb-12 grid gap-6 md:grid-cols-3">
        {[
          {
            icon: Network,
            title: "Use stronger hardware",
            description:
              "Run larger Whisper models on a workstation, mini PC, or server while a lightweight laptop stays responsive.",
          },
          {
            icon: Globe,
            title: "Open protocol choices",
            description:
              "Target OpenAI-compatible transcription services or the native whisper.cpp server endpoint.",
          },
          {
            icon: Settings,
            title: "Same desktop workflow",
            description:
              "Remote API behaves like a Vocalinux engine, so toggle mode, push-to-talk, VAD, and text injection still work normally.",
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

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-5 font-display text-2xl font-semibold">
          Supported Remote API Formats
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {protocolOptions.map((option) => (
            <article
              key={option.endpoint}
              className="rounded-[12px] border border-border bg-muted p-5"
            >
              <h3 className="mb-2 text-lg font-semibold">{option.name}</h3>
              <p className="mb-3 text-sm text-muted-foreground">
                {option.description}
              </p>
              <code className="rounded-md bg-[color:var(--terminal)] px-2.5 py-1.5 text-sm text-[color:var(--terminal-fg)]">
                {option.endpoint}
              </code>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-12 grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className="rounded-[12px] border border-border bg-muted p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <Terminal className="h-5 w-5 text-primary" />
            How the Request Flows
          </h2>
          <ol className="space-y-3 text-sm text-muted-foreground">
            {workflowSteps.map((step, index) => (
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
            <Lock className="h-5 w-5 text-primary" />
            Privacy and Security Notes
          </h2>
          <ul className="space-y-3 text-sm text-muted-foreground">
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
              Audio is not written to disk before upload.
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
              Use HTTPS and an API key outside a trusted local network.
            </li>
            <li className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
              Remote API is not on-device. Audio goes to the server you
              configure.
            </li>
          </ul>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-5 font-display text-2xl font-semibold">Remote API Setup Path</h2>
        <div className="grid gap-5 md:grid-cols-2">
          {setupSteps.map((step, index) => (
            <article
              key={step.title}
              className="rounded-[12px] border border-border bg-background p-6"
            >
              <span className="mb-4 inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                {index + 1}
              </span>
              <h3 className="mb-2 text-xl font-semibold">{step.title}</h3>
              <p className="text-sm text-muted-foreground">
                {step.description}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="border-primary/20 bg-primary/5 rounded-[12px] border p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Next Steps</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Link href="/advanced-settings/" className="group">
            <h3 className="font-semibold">Open advanced settings</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              See where Remote Server options live in the settings dialog.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Advanced guide <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/compare/" className="group">
            <h3 className="font-semibold">Compare all engines</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Decide when remote transcription beats local whisper.cpp, Whisper,
              or VOSK.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Engine comparison <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/privacy/" className="group">
            <h3 className="font-semibold">Review privacy tradeoffs</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Understand how local and remote recognition differ for sensitive
              dictation.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Privacy policy <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
