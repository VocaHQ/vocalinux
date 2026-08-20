import Link from "next/link";
import { type Metadata } from "next";
import { CheckCircle2, ChevronRight, DollarSign, Lock, Server, Shield, XCircle, Zap } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const alternatives = [
  {
    name: "Dragon Naturally Speaking",
    type: "Proprietary Desktop",
    pros: ["High accuracy", "Industry standard", "Advanced commands"],
    cons: ["No Linux support", "Expensive subscription", "Closed source", "Cloud dependency"],
    pricing: "$500/year+",
  },
  {
    name: "Otter.ai",
    type: "Cloud Service",
    pros: ["Good accuracy", "Meeting transcription", "Collaboration features"],
    cons: ["Cloud-only (no offline)", "Subscription required", "Privacy concerns", "No Linux desktop app"],
    pricing: "$10-30/month",
  },
  {
    name: "Google Voice Typing",
    type: "Cloud Service",
    pros: ["Free", "Good accuracy", "Multi-language"],
    cons: ["Requires Chrome/Google Docs", "Cloud-only", "Privacy concerns", "No Linux desktop integration"],
    pricing: "Free",
  },
  {
    name: "Speechnotes",
    type: "Web App",
    pros: ["Free tier available", "Simple to use", "No installation"],
    cons: ["Browser-only", "Limited offline support", "No desktop integration", "Privacy concerns"],
    pricing: "$10/month pro",
  },
  {
    name: "Windows Voice Typing",
    type: "OS Built-in",
    pros: ["Free", "Integrated with Windows", "Decent accuracy"],
    cons: ["Windows only", "No Linux support", "Limited customization", "Cloud processing"],
    pricing: "Free (Windows only)",
  },
];

const comparisonTable = [
  { feature: "Linux Support", vocalinux: true, dragon: false, otter: false, google: true },
  { feature: "Local engines", vocalinux: true, dragon: false, otter: false, google: false },
  { feature: "Open Source", vocalinux: true, dragon: false, otter: false, google: false },
  { feature: "Free Forever", vocalinux: true, dragon: false, otter: false, google: true },
  { feature: "Desktop Integration", vocalinux: true, dragon: true, otter: false, google: false },
  { feature: "Wayland Support", vocalinux: true, dragon: false, otter: false, google: false },
  { feature: "Custom Shortcuts", vocalinux: true, dragon: true, otter: false, google: false },
  { feature: "Voice Commands", vocalinux: true, dragon: true, otter: true, google: true },
  { feature: "Multi-language", vocalinux: true, dragon: true, otter: true, google: true },
  { feature: "GPU Acceleration", vocalinux: true, dragon: false, otter: false, google: false },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Vocalinux Alternatives - Linux Voice Dictation Comparison",
  description:
    "Compare Vocalinux to Dragon, Otter.ai, Google Voice Typing, and other speech-to-text alternatives. See why Vocalinux is the best choice for Linux voice dictation.",
  path: "/alternatives",
  keywords: [
    "vocalinux alternatives",
    "dragon naturally speaking linux alternative",
    "otter.ai alternative",
    "linux speech to text comparison",
    "offline voice dictation",
  ],
});

export default function AlternativesPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Vocalinux vs Dragon, Otter, Google - Voice Dictation Comparison",
    description:
      "Comprehensive comparison of Vocalinux with other voice dictation solutions for Linux users.",
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
    mainEntityOfPage: absoluteUrl("/alternatives"),
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
          Comparison
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Vocalinux vs The Alternatives
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Looking for voice dictation on Linux? Compare Vocalinux with Dragon, Otter.ai, Google Voice
          Typing, and other alternatives. See why Vocalinux is the best choice for Linux users.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-primary/20 bg-primary/5 p-6">
        <h2 className="mb-4 text-xl font-semibold">Why Vocalinux for Linux?</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="flex items-center gap-3">
            <Lock className="h-5 w-5 text-primary" />
            <span className="font-medium">Local engines</span>
          </div>
          <div className="flex items-center gap-3">
            <Shield className="h-5 w-5 text-primary" />
            <span className="font-medium">Privacy First</span>
          </div>
          <div className="flex items-center gap-3">
            <DollarSign className="h-5 w-5 text-primary" />
            <span className="font-medium">Free Forever</span>
          </div>
          <div className="flex items-center gap-3">
            <Server className="h-5 w-5 text-primary" />
            <span className="font-medium">Linux Native</span>
          </div>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6 overflow-x-auto">
        <h2 className="mb-6 font-display text-2xl font-semibold">Feature Comparison</h2>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border">
              <th className="pb-3 text-sm font-semibold">Feature</th>
              <th className="pb-3 text-sm font-semibold">Vocalinux</th>
              <th className="pb-3 text-sm font-semibold">Dragon</th>
              <th className="pb-3 text-sm font-semibold">Otter.ai</th>
              <th className="pb-3 text-sm font-semibold">Google</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {comparisonTable.map((row) => (
              <tr key={row.feature} className="border-b border-border">
                <td className="py-3 font-medium">{row.feature}</td>
                <td className="py-3">
                  {row.vocalinux ? (
                    <CheckCircle2 className="h-5 w-5 text-primary" aria-label="Yes" />
                  ) : (
                    <XCircle
                      className="h-5 w-5 text-[#c45c5c] dark:text-[#e08b8b]"
                      aria-label="No"
                    />
                  )}
                </td>
                <td className="py-3">
                  {row.dragon ? (
                    <CheckCircle2 className="h-5 w-5 text-primary" aria-label="Yes" />
                  ) : (
                    <XCircle
                      className="h-5 w-5 text-[#c45c5c] dark:text-[#e08b8b]"
                      aria-label="No"
                    />
                  )}
                </td>
                <td className="py-3">
                  {row.otter ? (
                    <CheckCircle2 className="h-5 w-5 text-primary" aria-label="Yes" />
                  ) : (
                    <XCircle
                      className="h-5 w-5 text-[#c45c5c] dark:text-[#e08b8b]"
                      aria-label="No"
                    />
                  )}
                </td>
                <td className="py-3">
                  {row.google ? (
                    <CheckCircle2 className="h-5 w-5 text-primary" aria-label="Yes" />
                  ) : (
                    <XCircle
                      className="h-5 w-5 text-[#c45c5c] dark:text-[#e08b8b]"
                      aria-label="No"
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-6">
        <h2 className="font-display text-2xl font-semibold">Detailed Comparison</h2>
        {alternatives.map((alt) => (
          <article
            key={alt.name}
            className="rounded-[12px] border border-border bg-background p-6"
          >
            <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="text-xl font-semibold">{alt.name}</h3>
                <p className="text-sm text-muted-foreground">{alt.type}</p>
              </div>
              <span className="rounded-full bg-muted px-3 py-1 text-sm font-medium bg-muted">
                {alt.pricing}
              </span>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-[12px] border border-border bg-muted/40 p-4">
                <p className="mb-2 text-sm font-semibold text-primary">Pros</p>
                <ul className="space-y-1.5">
                  {alt.pros.map((pro) => (
                    <li
                      key={pro}
                      className="flex items-start gap-2 text-sm text-muted-foreground"
                    >
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                      {pro}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="rounded-[12px] border border-border bg-muted/40 p-4">
                <p className="mb-2 text-sm font-semibold text-[#c45c5c] dark:text-[#e08b8b]">
                  Cons
                </p>
                <ul className="space-y-1.5">
                  {alt.cons.map((con) => (
                    <li
                      key={con}
                      className="flex items-start gap-2 text-sm text-muted-foreground"
                    >
                      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#c45c5c] dark:text-[#e08b8b]" />
                      {con}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </article>
        ))}
      </section>

      <section className="mt-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-3 font-display text-2xl font-semibold">Read the Nerd Dictation comparison</h2>
        <p className="mb-5 text-muted-foreground">
          Want a direct Linux-focused breakdown of CLI vs GUI workflows, Wayland behavior, and GPU
          support? Read our dedicated page.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link
            href="/vs-nerd-dictation/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Read the Nerd Dictation comparison
            <ChevronRight className="h-4 w-4" />
          </Link>
          <Link
            href="/compare/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted hover:bg-muted"
          >
            Engine comparison
          </Link>
        </div>
      </section>

      <section className="mt-12 rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">The Bottom Line</h2>
        <p className="mb-6 text-muted-foreground">
          If you are on Linux and need voice dictation, Vocalinux is a strong option: local
          engines, no usage telemetry, and desktop integration, at no cost. See the{" "}
          <Link href="/vs-nerd-dictation/" className="font-semibold hover:underline">
            nerd-dictation comparison
          </Link>{" "}
          for another free offline Linux tool.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/install/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Install Vocalinux
            <ChevronRight className="h-4 w-4" />
          </Link>
          <Link
            href="/privacy/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted hover:bg-muted"
          >
            <Lock className="h-4 w-4" />
            Our Privacy Commitment
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
