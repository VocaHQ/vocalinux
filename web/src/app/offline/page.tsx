import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  CloudOff,
  Database,
  Lock,
  Shield,
  WifiOff,
  XCircle,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const benefits = [
  {
    title: "Works without a network",
    description:
      "After the model is downloaded, local engines work with no internet. Remote API needs the server you configured.",
    icon: WifiOff,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Zero Data Collection",
    description:
      "No telemetry, no analytics, no usage tracking. Local engines have nowhere to send audio unless you enable Remote API.",
    icon: Database,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "No Account Required",
    description:
      "No signup, no login, no password to forget. Download and run - that's it.",
    icon: Lock,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Your Voice Stays Yours",
    description:
      "Voice data is biometric. Your voice patterns, accent, and speech habits are yours alone.",
    icon: Shield,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
];

const vsCloud = [
  { feature: "Requires internet for local dictation", offline: false, cloud: true },
  { feature: "Voice data uploaded to vendor servers", offline: false, cloud: true },
  { feature: "Account/signup required", offline: false, cloud: true },
  { feature: "Subscription cost", offline: false, cloud: true },
  { feature: "Works in airplane mode after model download", offline: true, cloud: false },
  { feature: "Vendor can shut down service", offline: false, cloud: true },
];

const sensitiveUseCases = [
  {
    title: "Local engines keep audio on the machine",
    description:
      "whisper.cpp, Whisper, and VOSK process speech on your hardware. That is a default for those engines, not a legal or compliance promise.",
  },
  {
    title: "Works after the model is downloaded",
    description:
      "Once the model is on disk, local engines keep working without a network. Remote API still needs the server you set.",
  },
  {
    title: "Remote API is opt-in",
    description:
      "If you point Vocalinux at a server you configure, audio goes there. Local engines do not.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Offline Voice Dictation - Local Engines | Vocalinux",
  description:
    "Local engines run on your Linux machine with no cloud account. Remote API is optional if you want a server you configure.",
  path: "/offline",
  keywords: [
    "offline voice dictation",
    "no cloud speech recognition",
    "private voice typing",
    "local speech to text",
    "offline dictation software",
    "no internet voice recognition",
    "airplane mode dictation",
    "privacy-first speech recognition",
  ],
});

export default function OfflinePage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Offline Voice Dictation for Linux",
    description:
      "Local engines process speech on your machine. Remote API is optional and talks only to a server you configure.",
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
    mainEntityOfPage: absoluteUrl("/offline"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <CloudOff className="h-4 w-4" />
          Offline
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Offline Voice Dictation
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Local engines keep speech recognition on your computer using whisper.cpp, VOSK, or
          OpenAI Whisper models on your hardware. Remote API is optional and talks only to a
          server you configure.
        </p>
      </section>

      <section className="mb-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {benefits.map((benefit) => {
          const Icon = benefit.icon;
          return (
            <article
              key={benefit.title}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <div className={`mb-3 inline-flex rounded-lg p-2 ${benefit.iconBg}`}>
                <Icon className={`h-5 w-5 ${benefit.iconColor}`} />
              </div>
              <h3 className="mb-2 font-semibold">{benefit.title}</h3>
              <p className="text-sm text-muted-foreground">{benefit.description}</p>
            </article>
          );
        })}
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-6 font-display text-2xl font-semibold">Offline vs Cloud Dictation</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Feature</th>
                <th className="pb-3 pr-4 font-semibold text-center">Vocalinux (Offline)</th>
                <th className="pb-3 font-semibold text-center">Cloud Dictation</th>
              </tr>
            </thead>
            <tbody>
              {vsCloud.map((row) => (
                <tr key={row.feature} className="border-b border-border">
                  <td className="py-3 pr-4">{row.feature}</td>
                  <td className="py-3 pr-4 text-center">
                    {row.offline ? (
                      <CheckCircle2 className="mx-auto h-5 w-5 text-primary" aria-label="Yes" />
                    ) : (
                      <XCircle
                        className="mx-auto h-5 w-5 text-muted-foreground/50"
                        aria-label="No"
                      />
                    )}
                  </td>
                  <td className="py-3 text-center">
                    {row.cloud ? (
                      <CheckCircle2 className="mx-auto h-5 w-5 text-primary" aria-label="Yes" />
                    ) : (
                      <XCircle
                        className="mx-auto h-5 w-5 text-muted-foreground/50"
                        aria-label="No"
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Local engines</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sensitiveUseCases.map((useCase) => (
            <div
              key={useCase.title}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 font-semibold">{useCase.title}</h3>
              <p className="text-sm text-muted-foreground">{useCase.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-primary/5 p-6">
        <h2 className="mb-3 text-xl font-semibold text-foreground">
          How Offline Processing Works
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Vocalinux uses speech recognition models that run entirely on your CPU or GPU:
        </p>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <strong>whisper.cpp</strong> - C++ port of OpenAI Whisper, runs locally with GPU
            acceleration
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <strong>VOSK</strong> - Lightweight offline engine, minimal resources
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <strong>OpenAI Whisper</strong> - PyTorch-based, runs on NVIDIA GPU or CPU
          </li>
        </ul>
        <p className="mt-4 text-sm text-muted-foreground">
          Models are downloaded once (74MB-3.0GB depending on size). After that, local engines
          process on the machine. Remote API is the exception: it sends audio to the server you
          configure.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-muted p-6">
        <h2 className="mb-3 text-xl font-semibold text-foreground">
          Verify It Yourself
        </h2>
        <p className="mb-3 text-sm text-muted-foreground">
          Don&apos;t trust - verify. Vocalinux is open source. You can:
        </p>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            Read every line of code on{" "}
            <a
              href="https://github.com/VocaHQ/vocalinux"
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold hover:underline"
            >
              GitHub
            </a>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            Run with <code className="rounded bg-muted px-1">--debug</code> and
            watch network activity. Local engines should stay quiet during dictation.
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            Monitor with <code className="rounded bg-muted px-1">tcpdump</code> or{" "}
            <code className="rounded bg-muted px-1">wireshark</code>. Local engines
            should stay quiet during dictation.
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            Disconnect from the internet and check that a local engine still dictates
          </li>
        </ul>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Truly Private Voice Dictation</h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux and use a local engine if you want speech recognition on the machine.
          Remote API stays optional.
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
            href="/open-source/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted hover:bg-muted"
          >
            View Source Code
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
