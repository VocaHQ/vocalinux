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
    title: "No Internet Required",
    description:
      "Works on airplanes, in tunnels, on remote farms. Your voice never needs to leave your machine.",
    icon: WifiOff,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Zero Data Collection",
    description:
      "No telemetry, no analytics, no usage tracking. There's no server to send data to even if we wanted to.",
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
  { feature: "Requires internet", offline: false, cloud: true },
  { feature: "Voice data uploaded to servers", offline: false, cloud: true },
  { feature: "Account/signup required", offline: false, cloud: true },
  { feature: "Subscription cost", offline: false, cloud: true },
  { feature: "Works in airplane mode", offline: true, cloud: false },
  { feature: "GDPR/privacy compliant by default", offline: true, cloud: false },
  { feature: "Vendor can shut down service", offline: false, cloud: true },
  { feature: "Sensitive content safe", offline: true, cloud: false },
];

const sensitiveUseCases = [
  {
    title: "Medical Professionals",
    description: "Patient notes, diagnoses, and medical records must stay private.",
  },
  {
    title: "Legal Professionals",
    description: "Attorney-client privilege requires absolute data confidentiality.",
  },
  {
    title: "Journalists & Sources",
    description: "Protecting sources means keeping all communications offline.",
  },
  {
    title: "Corporate Trade Secrets",
    description: "Product plans, financial data, and strategies shouldn't leave your network.",
  },
  {
    title: "Government & Defense",
    description: "Classified or sensitive government work requires air-gapped solutions.",
  },
  {
    title: "Personal Journals",
    description: "Your private thoughts and reflections deserve complete privacy.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "100% Offline Voice Dictation - No Cloud, No Upload | Vocalinux",
  description:
    "Completely offline voice dictation for Linux. No cloud processing, no data upload, no account required. Your voice data never leaves your computer.",
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
    headline: "100% Offline Voice Dictation for Linux",
    description:
      "Why Vocalinux is completely offline. No cloud processing, no data upload, maximum privacy.",
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
          100% Offline
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Offline Voice Dictation
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Your voice never leaves your computer. All speech recognition happens locally using
          whisper.cpp, VOSK, or OpenAI Whisper models running on your hardware. No cloud. No
          upload. No exceptions.
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
                      <CheckCircle2 className="mx-auto h-5 w-5 text-primary" />
                    ) : (
                      <XCircle className="mx-auto h-5 w-5 text-muted-foreground/50" />
                    )}
                  </td>
                  <td className="py-3 text-center">
                    {row.cloud ? (
                      <CheckCircle2 className="mx-auto h-5 w-5 text-primary" />
                    ) : (
                      <XCircle className="mx-auto h-5 w-5 text-muted-foreground/50" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">When Offline Matters Most</h2>
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
          Models are downloaded once (74MB-3.0GB depending on size), then all processing happens
          locally. No network requests during dictation.
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
            Run with <code className="rounded bg-muted px-1 dark:bg-muted">--debug</code> to see all network activity (there is none)
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            Monitor with <code className="rounded bg-muted px-1 dark:bg-muted">tcpdump</code> or{" "}
            <code className="rounded bg-muted px-1 dark:bg-muted">wireshark</code> - you&apos;ll see silence
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
            Disconnect from the internet and verify dictation still works perfectly
          </li>
        </ul>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Truly Private Voice Dictation</h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux and take control of your voice data. No cloud, no tracking, no
          compromises.
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
