import Link from "next/link";
import { type Metadata } from "next";
import { CheckCircle2, Lock, Server, Shield, Eye, Database, ExternalLink } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

export const metadata: Metadata = buildPageMetadata({
  title: "Privacy Policy - Local Voice Dictation",
  description:
    "Local engines keep audio on your computer. Remote API is optional and only talks to a server you configure.",
  path: "/privacy",
  keywords: [
    "vocalinux privacy",
    "offline voice dictation privacy",
    "speech to text data privacy",
    "linux dictation security",
  ],
});

export default function PrivacyPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Vocalinux Privacy Policy",
    description:
      "How Vocalinux handles voice data: local engines on your machine, optional Remote API to a server you configure.",
    dateModified: "2026-02-19",
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
    mainEntityOfPage: absoluteUrl("/privacy"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-primary/10 px-4 py-1.5 text-sm font-medium text-primary">
          <Shield className="h-4 w-4" />
          Privacy First
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          How Vocalinux handles your voice
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux is built for privacy. Local engines process speech on your machine. Remote API
          is optional and only talks to a server you set.
        </p>
      </section>

      {/* Key Privacy Points */}
      <section className="mb-12 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <article className="rounded-[12px] border border-border bg-background p-6">
          <div className="mb-4 inline-flex rounded-[12px] bg-primary/10 p-3">
            <Lock className="h-6 w-6 text-primary" />
          </div>
          <h3 className="mb-2 text-xl font-semibold">Local engines</h3>
          <p className="text-sm text-muted-foreground">
            Local engines do not need the internet after the model is downloaded. Processing stays
            on your device unless you turn on Remote API.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <div className="mb-4 inline-flex rounded-[12px] bg-primary/10 p-3">
            <Server className="h-6 w-6 text-primary" />
          </div>
          <h3 className="mb-2 text-xl font-semibold">No Cloud Processing</h3>
          <p className="text-sm text-muted-foreground">
            Local engines do not send your voice to our servers. Remote API sends audio only to the
            URL you configure.
          </p>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <div className="mb-4 inline-flex rounded-[12px] bg-primary/10 p-3">
            <Eye className="h-6 w-6 text-primary" />
          </div>
          <h3 className="mb-2 text-xl font-semibold">Open Source</h3>
          <p className="text-sm text-muted-foreground">
            Fully open source under AGPL-3.0. Inspect the code yourself on GitHub. No hidden
            telemetry or data collection.
          </p>
        </article>
      </section>

      {/* Detailed Privacy Sections */}
      <section className="space-y-8">
        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <Database className="h-5 w-5 text-primary" />
            Data Collection
          </h2>
          <div className="space-y-4 text-muted-foreground">
            <p>
              <strong className="text-foreground">We do not collect any personal data.</strong> This
              includes:
            </p>
            <ul className="space-y-2">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                No voice recordings or audio data
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                No transcribed text
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                No usage analytics or telemetry
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                No device fingerprints
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                No IP addresses or location data
              </li>
            </ul>
          </div>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <Shield className="h-5 w-5 text-primary" />
            How We Process Your Voice
          </h2>
          <div className="space-y-4 text-muted-foreground">
            <p>When you dictate, here's exactly what happens:</p>
            <ol className="space-y-3 pl-4">
              <li className="border-l-2 border-primary pl-4">
                <strong className="text-foreground">1. Audio Capture</strong> - Your microphone
                records audio temporarily in RAM
              </li>
              <li className="border-l-2 border-primary pl-4">
                <strong className="text-foreground">2. Local Processing</strong> - Audio is
                processed by whisper.cpp, Whisper, or VOSK on your CPU/GPU
              </li>
              <li className="border-l-2 border-primary pl-4">
                <strong className="text-foreground">3. Text Output</strong> - Transcribed text is
                injected into your active application
              </li>
              <li className="border-l-2 border-primary pl-4">
                <strong className="text-foreground">4. Immediate Deletion</strong> - Audio data is
                discarded immediately after processing
              </li>
            </ol>
            <p className="mt-4 rounded-lg bg-muted p-4 text-sm">
              <strong>Note:</strong> Local engines do not write audio to disk or send it over the
              network. Remote API sends audio to the server you configure.
            </p>
          </div>
        </article>

        <article className="rounded-[12px] border border-border bg-background p-6">
          <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
            <Lock className="h-5 w-5 text-primary" />
            Configuration Data
          </h2>
          <div className="space-y-4 text-muted-foreground">
            <p>
              Vocalinux stores configuration locally at <code className="rounded bg-muted px-1.5 py-0.5 bg-muted">~/.config/vocalinux/</code>:
            </p>
            <ul className="space-y-2">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Settings like preferred engine, model size, and language
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Custom keyboard shortcuts
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Window and tray preferences
              </li>
            </ul>
            <p>
              This data is stored in plain text YAML format. You can view, edit, or delete it at
              any time.
            </p>
          </div>
        </article>
      </section>

      {/* Comparison with Cloud Services */}
      <section className="mt-12 rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-6 font-display text-2xl font-semibold">Vocalinux vs Cloud Dictation Services</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 text-sm font-semibold">Feature</th>
                <th className="pb-3 text-sm font-semibold">Vocalinux</th>
                <th className="pb-3 text-sm font-semibold">Cloud Services</th>
              </tr>
            </thead>
            <tbody className="text-sm text-muted-foreground">
              <tr className="border-b border-border">
                <td className="py-3 font-medium text-foreground">Data leaves device</td>
                <td className="py-3 text-primary">
                  Only with Remote API
                </td>
                <td className="py-3 text-primary">Always</td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-3 font-medium text-foreground">Internet required</td>
                <td className="py-3 text-primary">
                  Only for Remote API or a model download
                </td>
                <td className="py-3 text-primary">Yes</td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-3 font-medium text-foreground">Source code available</td>
                <td className="py-3 text-primary">Yes (AGPL-3.0)</td>
                <td className="py-3 text-primary">No</td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-3 font-medium text-foreground">Voice recordings stored</td>
                <td className="py-3 text-primary">No</td>
                <td className="py-3">Varies by service</td>
              </tr>
              <tr>
                <td className="py-3 font-medium text-foreground">Cost</td>
                <td className="py-3 text-primary">Free forever</td>
                <td className="py-3">Subscription</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Contact */}
      <section className="mt-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 text-xl font-semibold">Questions About Privacy?</h2>
        <p className="mb-4 text-muted-foreground">
          If you have any questions about our privacy practices or want to verify our claims,
          please reach out:
        </p>
        <a
          href="https://github.com/VocaHQ/vocalinux/issues"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-primary hover:underline"
        >
          Open an issue on GitHub
          <ExternalLink className="h-4 w-4" />
        </a>
      </section>
    </SeoSubpageShell>
  );
}
