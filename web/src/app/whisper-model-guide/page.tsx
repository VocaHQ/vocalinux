import Link from "next/link";
import { type Metadata } from "next";
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Gauge,
  Rocket,
  Sparkles,
  Zap,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const modelComparison = [
  {
    model: "Tiny",
    size: "~74MB",
    ramCpu: "~0.8-1.2GB",
    ramGpu: "~0.5-0.8GB VRAM",
    accuracy: "Good",
    speed: "Fastest",
    bestFor: "Older laptops, lowest latency, quick notes",
  },
  {
    model: "Base",
    size: "~141MB",
    ramCpu: "~1.2-1.8GB",
    ramGpu: "~0.8-1.2GB VRAM",
    accuracy: "Good+",
    speed: "Very fast",
    bestFor: "Balanced real-time dictation on most systems",
  },
  {
    model: "Small",
    size: "~465MB",
    ramCpu: "~2-3GB",
    ramGpu: "~1.5-2.5GB VRAM",
    accuracy: "High",
    speed: "Fast",
    bestFor: "Most users wanting stronger punctuation and names",
  },
  {
    model: "Medium",
    size: "~1.5GB",
    ramCpu: "~4-6GB",
    ramGpu: "~3-5GB VRAM",
    accuracy: "Very high",
    speed: "Moderate",
    bestFor: "Accuracy-focused dictation, technical writing",
  },
  {
    model: "Large",
    size: "~3.0GB",
    ramCpu: "~8GB+",
    ramGpu: "~6-10GB VRAM",
    accuracy: "Best",
    speed: "Slowest",
    bestFor: "Maximum quality with strong GPU hardware",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Whisper Model Sizes: Tiny to Large for Linux Dictation",
  description:
    "Complete guide to Whisper model sizes for Linux voice dictation. Compare tiny vs base vs small vs medium vs large models - download size, RAM usage, accuracy, GPU requirements, and speed.",
  path: "/whisper-model-guide",
  keywords: [
    "whisper model sizes",
    "whisper tiny vs base",
    "which whisper model",
    "whisper.cpp models",
    "linux dictation model selection",
  ],
});

export default function WhisperModelGuidePage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Whisper Model Sizes Explained: Tiny, Base, Small, Medium, Large for Linux",
    description:
      "Complete guide to Whisper model sizes for Linux voice dictation. Compare tiny vs base vs small vs medium vs large models for size, memory, speed, and accuracy.",
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
    mainEntityOfPage: absoluteUrl("/whisper-model-guide"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Sparkles className="h-4 w-4" />
          Whisper Model Guide
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Whisper Model Sizes Explained: Tiny, Base, Small, Medium, Large for Linux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Picking the right model is the biggest performance decision for Linux voice dictation.
          Use this guide to choose between tiny, base, small, medium, and large based on RAM,
          speed, and real-world transcription accuracy in Vocalinux.
        </p>
      </section>

      <section className="overflow-x-auto rounded-[12px] border border-border bg-background">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-3 text-sm font-semibold">Model</th>
              <th className="px-4 py-3 text-sm font-semibold">Size</th>
              <th className="px-4 py-3 text-sm font-semibold">RAM (CPU)</th>
              <th className="px-4 py-3 text-sm font-semibold">RAM (GPU)</th>
              <th className="px-4 py-3 text-sm font-semibold">Accuracy</th>
              <th className="px-4 py-3 text-sm font-semibold">Speed</th>
              <th className="px-4 py-3 text-sm font-semibold">Best For</th>
            </tr>
          </thead>
          <tbody>
            {modelComparison.map((row) => (
              <tr
                key={row.model}
                className="border-b border-border align-top"
              >
                <td className="px-4 py-4 font-semibold">{row.model}</td>
                <td className="px-4 py-4 text-sm text-muted-foreground">{row.size}</td>
                <td className="px-4 py-4 text-sm text-muted-foreground">{row.ramCpu}</td>
                <td className="px-4 py-4 text-sm text-muted-foreground">{row.ramGpu}</td>
                <td className="px-4 py-4 text-sm text-muted-foreground">{row.accuracy}</td>
                <td className="px-4 py-4 text-sm text-muted-foreground">{row.speed}</td>
                <td className="px-4 py-4 text-sm text-muted-foreground">{row.bestFor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="mt-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Which model should you choose?</h2>
        <div className="grid gap-6 md:grid-cols-2">
          <article className="rounded-[12px] border border-border bg-background p-6">
            <h3 className="mb-3 inline-flex items-center gap-2 text-xl font-semibold">
              <Zap className="h-5 w-5 text-primary" />
              Tiny or Base
            </h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Best if you care about low latency over absolute transcription quality.
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Great for older CPUs, battery-conscious laptops, and quick chat replies.
              </li>
            </ul>
          </article>

          <article className="rounded-[12px] border border-border bg-background p-6">
            <h3 className="mb-3 inline-flex items-center gap-2 text-xl font-semibold">
              <Gauge className="h-5 w-5 text-primary" />
              Small (recommended default)
            </h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Best balance for most Linux dictation workflows.
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Better punctuation and proper nouns while staying near real-time.
              </li>
            </ul>
          </article>

          <article className="rounded-[12px] border border-border bg-background p-6">
            <h3 className="mb-3 inline-flex items-center gap-2 text-xl font-semibold">
              <Cpu className="h-5 w-5 text-primary" />
              Medium
            </h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Use when accuracy is more important than response time.
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Ideal for technical dictation, multilingual speech, and noisy environments.
              </li>
            </ul>
          </article>

          <article className="rounded-[12px] border border-border bg-background p-6">
            <h3 className="mb-3 inline-flex items-center gap-2 text-xl font-semibold">
              <Rocket className="h-5 w-5 text-primary" />
              Large
            </h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Choose only if you have strong GPU hardware and want maximum quality.
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Best for polished long-form writing where errors are costly.
              </li>
            </ul>
          </article>
        </div>
      </section>

      <section className="mt-12 grid gap-6 md:grid-cols-3">
        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-xl font-semibold">Need more speed?</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            Enable GPU acceleration to run larger models faster, especially medium and large.
          </p>
          <Link href="/gpu-acceleration/" className="inline-flex items-center gap-1 text-primary hover:underline">
            GPU acceleration guide <ArrowRight className="h-4 w-4" />
          </Link>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-xl font-semibold">Comparing engines?</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            See whisper.cpp vs Whisper vs VOSK before deciding your full dictation stack.
          </p>
          <Link href="/compare/" className="inline-flex items-center gap-1 text-primary hover:underline">
            Engine comparison <ArrowRight className="h-4 w-4" />
          </Link>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-xl font-semibold">Ready to install?</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            Use the install guide to get Vocalinux running with the model size that fits your hardware.
          </p>
          <Link href="/install/" className="inline-flex items-center gap-1 text-primary hover:underline">
            Installation guide <ArrowRight className="h-4 w-4" />
          </Link>
        </article>
      </section>

      <section className="mt-12 rounded-[12px] border border-primary/30 bg-primary/10 p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Install Vocalinux and start dictating today</h2>
        <p className="mb-6 max-w-3xl text-muted-foreground">
          Start with <strong>small</strong> if unsure, then move up or down after a day of use.
          Vocalinux makes model changes simple, so you can tune for your exact speed/accuracy
          preference.
        </p>
        <Link
          href="/install/"
          className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
        >
          Install Vocalinux
          <ArrowRight className="h-4 w-4" />
        </Link>
      </section>
    </SeoSubpageShell>
  );
}
