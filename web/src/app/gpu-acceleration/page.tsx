import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Cpu,
  Gauge,
  MemoryStick,
  Monitor,
  Zap,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const gpuBackends = [
  {
    name: "Vulkan",
    supportedGPUs: "AMD, Intel, NVIDIA",
    description:
      "Cross-platform GPU API supported by all major GPU vendors. The default and most compatible backend for whisper.cpp.",
    advantages: [
      "Works with AMD, Intel, and NVIDIA GPUs",
      "No vendor-specific drivers required",
      "Excellent Linux support",
      "Best option for AMD and Intel GPUs",
    ],
    icon: Monitor,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    recommended: true,
  },
  {
    name: "CUDA",
    supportedGPUs: "NVIDIA only",
    description:
      "NVIDIA's proprietary GPU compute platform. High performance but requires NVIDIA GPU and CUDA toolkit.",
    advantages: [
      "Excellent performance on NVIDIA hardware",
      "Mature ecosystem and tooling",
      "Works with PyTorch-based Whisper engine",
    ],
    icon: Cpu,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    recommended: false,
  },
  {
    name: "CPU",
    supportedGPUs: "All systems",
    description:
      "Pure CPU processing. Slower but works on any system. Automatic fallback when GPU is unavailable.",
    advantages: [
      "Works on any hardware",
      "No GPU requirements",
      "Predictable performance",
      "Lowest power consumption option",
    ],
    icon: MemoryStick,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    recommended: false,
  },
];

const modelPerformance = [
  {
    model: "tiny",
    size: "~74MB",
    cpuSpeed: "~0.5s",
    gpuSpeed: "~0.2s",
    accuracy: "Good for real-time",
    recommended: "Real-time dictation, older hardware",
  },
  {
    model: "base",
    size: "~141MB",
    cpuSpeed: "~0.8s",
    gpuSpeed: "~0.3s",
    accuracy: "Better accuracy",
    recommended: "Balanced speed/accuracy",
  },
  {
    model: "small",
    size: "~465MB",
    cpuSpeed: "~1.5s",
    gpuSpeed: "~0.5s",
    accuracy: "High accuracy",
    recommended: "Most users, good balance",
  },
  {
    model: "medium",
    size: "~1.5GB",
    cpuSpeed: "~4s",
    gpuSpeed: "~1.2s",
    accuracy: "Very high accuracy",
    recommended: "Accuracy-focused use, with GPU",
  },
  {
    model: "large",
    size: "~3.0GB",
    cpuSpeed: "~8s",
    gpuSpeed: "~2.5s",
    accuracy: "Best accuracy",
    recommended: "Maximum accuracy, requires GPU",
  },
];

const hardwareRequirements = [
  {
    category: "Minimum (CPU-only)",
    ram: "4GB RAM",
    storage: "200MB",
    gpu: "None required",
    performance: "Functional but slower processing",
  },
  {
    category: "Recommended (with GPU)",
    ram: "8GB RAM",
    storage: "500MB",
    gpu: "Any Vulkan-compatible GPU",
    performance: "Real-time dictation with small/base models",
  },
  {
    category: "Optimal",
    ram: "16GB+ RAM",
    storage: "2GB+",
    gpu: "NVIDIA RTX or AMD RX series",
    performance: "Real-time with any model including large",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Vulkan GPU Speech to Text on Linux: AMD, Intel, NVIDIA",
  description:
    "Run whisper.cpp speech recognition on your GPU with Vulkan on Linux: AMD, Intel and NVIDIA. CPU vs GPU speed, model sizes, and automatic CPU fallback.",
  path: "/gpu-acceleration",
  keywords: [
    "GPU voice dictation",
    "Vulkan speech recognition",
    "AMD GPU dictation",
    "NVIDIA CUDA voice typing",
    "Intel GPU speech to text",
    "hardware accelerated dictation",
    "Linux GPU speech recognition",
    "whisper.cpp GPU",
  ],
});

export default function GpuAccelerationPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "GPU Accelerated Voice Dictation for Linux",
    description:
      "Complete guide to GPU acceleration in Vocalinux. Vulkan support for AMD, Intel, and NVIDIA GPUs.",
    dateModified: "2026-02-22",
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
    mainEntityOfPage: absoluteUrl("/gpu-acceleration"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Zap className="h-4 w-4" />
          Performance
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          GPU Accelerated Voice Dictation
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Leverage your GPU for faster speech recognition. Vocalinux supports AMD, Intel, and NVIDIA
          GPUs via Vulkan - with automatic fallback to CPU when needed.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-primary/20 bg-primary/5 p-6">
        <h2 className="mb-4 text-xl font-semibold">Quick Check: Do You Have GPU Support?</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Run this command to check if your system supports Vulkan GPU acceleration:
        </p>
        <div className="rounded-lg bg-[color:var(--terminal)] p-4">
          <code className="text-sm text-[color:var(--terminal-fg)]">vulkaninfo --summary | grep deviceName</code>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          If you see your GPU name, you&apos;re ready for accelerated dictation!
          On multi-GPU machines Vocalinux prefers a discrete Vulkan device when
          one is present; pick a specific device under Advanced settings if you
          need to override auto-select.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Supported GPU Backends</h2>
        <div className="space-y-6">
          {gpuBackends.map((backend) => {
            const Icon = backend.icon;
            return (
              <article
                key={backend.name}
                className={`rounded-[12px] border p-6 ${
                  backend.recommended
                    ? "border-primary/50 bg-primary/5"
                    : "border-border bg-background  "
                }`}
              >
                <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className={`rounded-lg p-2.5 ${backend.iconBg}`}>
                      <Icon className={`h-5 w-5 ${backend.iconColor}`} />
                    </div>
                    <div>
                      <h3 className="font-semibold">{backend.name}</h3>
                      <p className="text-sm text-muted-foreground">{backend.supportedGPUs}</p>
                    </div>
                  </div>
                  {backend.recommended && (
                    <span className="rounded-full bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground">
                      Recommended
                    </span>
                  )}
                </div>
                <p className="mb-4 text-sm text-muted-foreground">{backend.description}</p>
                <ul className="space-y-1.5">
                  {backend.advantages.map((advantage) => (
                    <li key={advantage} className="flex items-start gap-2 text-sm">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                      {advantage}
                    </li>
                  ))}
                </ul>
              </article>
            );
          })}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-6 font-display text-2xl font-semibold">Model Performance Comparison</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Approximate transcription times for 5 seconds of audio. GPU times assume a mid-range
          Vulkan-compatible GPU.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Model</th>
                <th className="pb-3 pr-4 font-semibold">Size</th>
                <th className="pb-3 pr-4 font-semibold">CPU Time</th>
                <th className="pb-3 pr-4 font-semibold">GPU Time</th>
                <th className="pb-3 pr-4 font-semibold">Accuracy</th>
                <th className="pb-3 font-semibold">Best For</th>
              </tr>
            </thead>
            <tbody>
              {modelPerformance.map((row) => (
                <tr key={row.model} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{row.model}</td>
                  <td className="py-3 pr-4 text-muted-foreground">{row.size}</td>
                  <td className="py-3 pr-4 text-muted-foreground">{row.cpuSpeed}</td>
                  <td className="py-3 pr-4 text-muted-foreground">{row.gpuSpeed}</td>
                  <td className="py-3 pr-4 text-muted-foreground">{row.accuracy}</td>
                  <td className="py-3 text-muted-foreground">{row.recommended}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Hardware Requirements</h2>
        <div className="grid gap-6 sm:grid-cols-3">
          {hardwareRequirements.map((tier) => (
            <article
              key={tier.category}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-3 font-semibold">{tier.category}</h3>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">RAM</dt>
                  <dd className="font-medium">{tier.ram}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Storage</dt>
                  <dd className="font-medium">{tier.storage}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">GPU</dt>
                  <dd className="font-medium">{tier.gpu}</dd>
                </div>
              </dl>
              <p className="mt-4 text-xs text-muted-foreground">{tier.performance}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-muted p-6">
        <div className="flex items-start gap-3">
          <Gauge className="mt-0.5 h-5 w-5 flex-shrink-0 text-muted-foreground" />
          <div>
            <h3 className="mb-2 font-semibold text-foreground">
              Intel GPU Note
            </h3>
            <p className="text-sm text-muted-foreground">
              Some Intel integrated GPUs don&apos;t fully support the compute features needed for
              whisper.cpp GPU acceleration. Vocalinux v0.7.0+ automatically detects incompatible
              Intel GPUs and falls back to CPU processing for reliability.
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Get Started with GPU Acceleration</h2>
        <p className="mb-6 text-muted-foreground">
          The installer automatically detects your GPU and configures the best backend. Just run
          and go.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/install/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Install Now
            <ChevronRight className="h-4 w-4" />
          </Link>
          <Link
            href="/compare/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted hover:bg-muted"
          >
            Compare Engines
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
