import Link from "next/link";
import { type Metadata } from "next";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Cpu,
  RotateCcw,
  Server,
  Settings,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, AUTHOR_PERSON, buildPageMetadata } from "@/lib/seo";

const whisperControls = [
  {
    name: "No Timestamps",
    detail:
      "Disables timestamp token generation to reduce timestamp-related hallucinations.",
  },
  {
    name: "No Context",
    detail:
      "Stops whisper.cpp from conditioning on previous text when past context causes error loops.",
  },
  {
    name: "Temperature",
    detail:
      "Controls decoding randomness. The default 0.0 keeps dictation deterministic.",
  },
  {
    name: "Temperature Increment",
    detail:
      "Sets fallback steps for retry behavior, or disables fallback entirely with -1.0.",
  },
  {
    name: "Entropy Threshold",
    detail: "Helps detect repetition loops during decoding.",
  },
  {
    name: "Logprob Threshold",
    detail: "Triggers fallback when average token confidence is too low.",
  },
  {
    name: "No-Speech Threshold",
    detail: "Controls how strongly whisper.cpp treats audio as silence.",
  },
  {
    name: "Initial Prompt",
    detail:
      "Adds names, jargon, punctuation style, or other context to steer transcription.",
  },
];

const useCases = [
  "Suppress repeated phrases or timestamp artifacts in long dictation sessions.",
  "Bias transcription toward project names, technical jargon, or personal vocabulary.",
  "Keep whisper.cpp deterministic for notes, code comments, and messages.",
  "Move Remote Server settings out of the way until power-user mode is enabled.",
];

export const metadata: Metadata = buildPageMetadata({
  title: "Advanced Whisper.cpp Settings for Linux Dictation",
  description:
    "Tune Vocalinux advanced whisper.cpp settings for anti-hallucination, decoding thresholds, initial prompts, and Remote API configuration.",
  path: "/advanced-settings",
  keywords: [
    "whisper.cpp advanced settings",
    "whisper anti hallucination linux dictation",
    "vocalinux advanced settings",
    "whisper.cpp no speech threshold",
  ],
});

export default function AdvancedSettingsPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Advanced Whisper.cpp Settings for Linux Dictation",
    description:
      "Guide to Vocalinux advanced settings for whisper.cpp decoding, anti-hallucination controls, and Remote API configuration.",
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
    mainEntityOfPage: absoluteUrl("/advanced-settings"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="border-primary/30 bg-primary/10 mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium text-primary">
          <SlidersHorizontal className="h-4 w-4" />
          Advanced settings
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Advanced Whisper.cpp Settings for Linux Dictation
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux keeps the default setup simple, but power users can unlock
          advanced whisper.cpp decoding controls for anti-hallucination tuning,
          initial prompts, Remote API server configuration, Vulkan GPU device
          selection, and optional model keep-alive unload.
        </p>
      </section>

      <section className="mb-12 grid gap-6 md:grid-cols-3">
        {[
          {
            icon: Sparkles,
            title: "Anti-hallucination controls",
            description:
              "Tune timestamp, context, confidence, and silence thresholds when a specific setup needs stricter decoding.",
          },
          {
            icon: Server,
            title: "Remote Server options",
            description:
              "Configure the Remote API URL, optional bearer token, and endpoint format from the same advanced area.",
          },
          {
            icon: RotateCcw,
            title: "Resettable power-user mode",
            description:
              "Advanced options are opt-in and can be reset when experimentation produces worse dictation.",
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
        <h2 className="mb-5 flex items-center gap-2 font-display text-2xl font-semibold">
          <Cpu className="h-5 w-5 text-primary" />
          Whisper.cpp Decoding Controls
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {whisperControls.map((control) => (
            <article
              key={control.name}
              className="rounded-[12px] border border-border bg-muted p-5"
            >
              <h3 className="mb-2 text-lg font-semibold">{control.name}</h3>
              <p className="text-sm text-muted-foreground">{control.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-12 grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className="rounded-[12px] border border-border bg-muted p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <Settings className="h-5 w-5 text-primary" />
            When to Use Advanced Settings
          </h2>
          <ul className="space-y-3 text-sm text-muted-foreground">
            {useCases.map((useCase) => (
              <li key={useCase} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                <span>{useCase}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-[12px] border border-border bg-muted p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <AlertTriangle className="h-5 w-5 text-muted-foreground" />
            Keep Defaults Unless You Need Them
          </h2>
          <p className="text-sm text-muted-foreground">
            The default whisper.cpp settings are chosen for reliable everyday
            dictation. Advanced values can improve niche workflows, but they can
            also reduce accuracy if pushed too far. Change one value at a time
            and reset if quality drops.
          </p>
        </div>
      </section>

      <section className="border-primary/20 bg-primary/5 rounded-[12px] border p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Related Guides</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Link href="/voice-activity-detection/" className="group">
            <h3 className="font-semibold">Silero VAD</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Learn how speech and silence are filtered before recognition.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              VAD guide <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/remote-api/" className="group">
            <h3 className="font-semibold">Remote API</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Configure self-hosted or compatible remote transcription servers.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Remote guide <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
          <Link href="/whisper-model-guide/" className="group">
            <h3 className="font-semibold">Whisper model guide</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Choose model sizes before tuning advanced decoding behavior.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary group-hover:underline">
              Model guide <ChevronRight className="h-4 w-4" />
            </span>
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
