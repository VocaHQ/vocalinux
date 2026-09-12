import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Cpu,
  Server,
  Sparkles,
  Zap,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const engineTable = [
  {
    engine: "whisper.cpp",
    speed: "Fastest startup + low latency",
    hardware: "CPU + AMD/Intel/NVIDIA GPU",
    accuracy: "High (best overall balance)",
    footprint: "Small models available (~74MB tiny)",
    bestFor: "Most users who want strong speed + quality",
    icon: Zap,
    iconColor: "text-primary",
    iconBg: "bg-muted",
  },
  {
    engine: "Whisper (OpenAI)",
    speed: "Slower install and startup",
    hardware: "CPU or NVIDIA CUDA",
    accuracy: "High",
    footprint: "Large dependency footprint (~2.3GB)",
    bestFor: "Users already standardized on PyTorch stack",
    icon: Sparkles,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    engine: "Faster Whisper",
    speed: "Fast CPU inference (CTranslate2 / INT8)",
    hardware: "CPU",
    accuracy: "High (Whisper-class)",
    footprint: "Optional extra; not in AppImage/Flatpak/Snap",
    bestFor: "CPU-only machines that want Whisper quality without PyTorch",
    icon: Sparkles,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    engine: "VOSK",
    speed: "Very fast realtime on low-end systems",
    hardware: "CPU",
    accuracy: "Good for lightweight use",
    footprint: "Very lightweight (~40MB model)",
    bestFor: "Older hardware and minimal-resource environments",
    icon: Cpu,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    engine: "Parakeet",
    speed: "Fast CPU (sherpa-onnx TDT 0.6B)",
    hardware: "CPU",
    accuracy: "High on bundled English / European languages",
    footprint: "Large download (~639MB v3-european default)",
    bestFor: "English or European dictation without the Whisper catalog picker",
    icon: Cpu,
    iconColor: "text-primary",
    iconBg: "bg-muted",
  },
  {
    engine: "Remote API",
    speed: "Depends on server + network latency",
    hardware: "Client CPU + remote Whisper server",
    accuracy: "Depends on remote model",
    footprint: "No local model required",
    bestFor: "Powerful LAN servers or shared transcription backends",
    icon: Server,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Whisper.cpp vs Whisper vs VOSK vs Remote API for Linux",
  description:
    "Compare whisper.cpp, Whisper, VOSK, and Remote API for Linux speech-to-text. See speed, hardware requirements, privacy tradeoffs, and best use cases.",
  path: "/compare",
  keywords: [
    "whisper.cpp vs vosk",
    "remote api speech recognition linux",
    "linux speech recognition comparison",
    "best voice dictation engine linux",
    "whisper vs vosk linux",
  ],
});

export default function CompareEnginesPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline:
      "Whisper.cpp vs Whisper vs VOSK vs Remote API for Linux Voice Dictation",
    description:
      "Technical comparison of local and remote speech recognition engines for Linux voice typing.",
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
    mainEntityOfPage: absoluteUrl("/compare"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="border-primary/30 bg-primary/10 mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium text-primary">
          <Sparkles className="h-4 w-4" />
          Speech Engine Comparison
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          whisper.cpp vs Whisper vs VOSK vs Remote API on Linux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          If you are choosing a Linux speech-to-text engine, this page gives a
          practical side-by-side comparison focused on latency, hardware
          support, install footprint, privacy boundary, and real desktop usage.
        </p>
      </section>

      <section className="space-y-4 md:hidden">
        {engineTable.map((row) => {
          const Icon = row.icon;
          return (
            <article
              key={row.engine}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <div className="mb-4 flex items-center gap-3">
                <span className={`inline-flex rounded-md p-2 ${row.iconBg}`}>
                  <Icon className={`h-5 w-5 ${row.iconColor}`} />
                </span>
                <h2 className="text-xl font-semibold">{row.engine}</h2>
              </div>
              <dl className="grid gap-3 text-sm">
                {[
                  ["Speed", row.speed],
                  ["Hardware", row.hardware],
                  ["Accuracy", row.accuracy],
                  ["Footprint", row.footprint],
                  ["Best for", row.bestFor],
                ].map(([label, value]) => (
                  <div key={label} className="grid gap-1">
                    <dt className="text-xs font-semibold uppercase text-muted-foreground">
                      {label}
                    </dt>
                    <dd className="text-foreground">{value}</dd>
                  </div>
                ))}
              </dl>
            </article>
          );
        })}
      </section>

      <section className="hidden overflow-x-auto rounded-[12px] border border-border bg-background md:block">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-3 text-sm font-semibold">Engine</th>
              <th className="px-4 py-3 text-sm font-semibold">Speed</th>
              <th className="px-4 py-3 text-sm font-semibold">Hardware</th>
              <th className="px-4 py-3 text-sm font-semibold">Accuracy</th>
              <th className="px-4 py-3 text-sm font-semibold">Footprint</th>
              <th className="px-4 py-3 text-sm font-semibold">Best for</th>
            </tr>
          </thead>
          <tbody>
            {engineTable.map((row) => {
              const Icon = row.icon;
              return (
                <tr
                  key={row.engine}
                  className="border-b border-border align-top"
                >
                  <td className="px-4 py-4 font-semibold">
                    <span className="inline-flex items-center gap-2">
                      <span
                        className={`inline-flex rounded-md p-1.5 ${row.iconBg}`}
                      >
                        <Icon className={`h-4 w-4 ${row.iconColor}`} />
                      </span>
                      {row.engine}
                    </span>
                  </td>
                  <td className="px-4 py-4 text-sm text-muted-foreground">
                    {row.speed}
                  </td>
                  <td className="px-4 py-4 text-sm text-muted-foreground">
                    {row.hardware}
                  </td>
                  <td className="px-4 py-4 text-sm text-muted-foreground">
                    {row.accuracy}
                  </td>
                  <td className="px-4 py-4 text-sm text-muted-foreground">
                    {row.footprint}
                  </td>
                  <td className="px-4 py-4 text-sm text-muted-foreground">
                    {row.bestFor}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="mt-8 rounded-[12px] border border-border bg-muted p-6">
        <h2 className="mb-3 text-2xl font-semibold">
          Switching Between Engines
        </h2>
        <p className="text-sm text-muted-foreground">
          You can switch between whisper.cpp, Faster Whisper, Whisper, VOSK,
          Parakeet, and Remote API from Settings. Speech Model simple setup
          (v0.17.0) puts language and speed/accuracy first; engine choice lives
          under Advanced. v0.10.1+ safely stops recognition before switching.
        </p>
      </section>

      <section className="mt-12 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">
            When to pick whisper.cpp
          </h2>
          <p className="text-sm text-muted-foreground">
            Choose whisper.cpp when you want the best speed-to-accuracy ratio
            and broad hardware support. It is the default in Vocalinux for a
            reason. Safe engine switching - v0.10.1+ stops recognition before
            switching to prevent crashes.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">When to pick Whisper</h2>
          <p className="text-sm text-muted-foreground">
            Choose OpenAI Whisper if your environment already depends on
            PyTorch/CUDA workflows and you prefer that runtime profile.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">When to pick Faster Whisper</h2>
          <p className="text-sm text-muted-foreground">
            Choose Faster Whisper for Whisper-class accuracy on CPU without the
            PyTorch stack. Optional extra; not bundled in AppImage, Flatpak, or Snap.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">When to pick VOSK</h2>
          <p className="text-sm text-muted-foreground">
            Choose VOSK on older laptops, low-RAM systems, or lightweight VMs
            where small model size and minimal overhead matter most.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">When to pick Parakeet</h2>
          <p className="text-sm text-muted-foreground">
            Choose Parakeet for English or European dictation on CPU via
            sherpa-onnx. It uses a bundled language set (v3-european default)
            instead of the Whisper catalog picker. Optional extra; not in
            AppImage, Flatpak, or Snap.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-3 text-2xl font-semibold">
            When to pick Remote API
          </h2>
          <p className="text-sm text-muted-foreground">
            Choose Remote API when a trusted server has stronger hardware,
            larger models, or a shared Whisper backend. Use local engines when
            your voice data must stay entirely on-device.
          </p>
          <Link
            href="/remote-api/"
            className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline"
          >
            Remote setup <ChevronRight className="h-4 w-4" />
          </Link>
        </article>
      </section>

      <section className="mt-12 rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Next steps</h2>
        <ul className="space-y-3 text-muted-foreground">
          <li className="flex gap-2">
            <CheckCircle2 className="mt-1 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              Install by distro:
              <Link
                href="/install/ubuntu/"
                className="font-semibold text-primary hover:underline"
              >
                Ubuntu
              </Link>
              ,
              <Link
                href="/install/fedora/"
                className="font-semibold text-primary hover:underline"
              >
                Fedora
              </Link>
              ,
              <Link
                href="/install/arch/"
                className="font-semibold text-primary hover:underline"
              >
                Arch Linux
              </Link>
              .
            </span>
          </li>
          <li className="flex gap-2">
            <CheckCircle2 className="mt-1 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              Use interactive install to detect your hardware and pick the best
              engine defaults.
            </span>
          </li>
          <li className="flex gap-2">
            <CheckCircle2 className="mt-1 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              After install, tune model size, VAD sensitivity, or Remote API
              settings for your preferred latency and accuracy level.
            </span>
          </li>
        </ul>
      </section>
    </SeoSubpageShell>
  );
}
