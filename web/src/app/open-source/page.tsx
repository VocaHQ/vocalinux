import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Code,
  Eye,
  GitBranch,
  Heart,
  Lock,
  Scale,
  Shield,
  Users,
  Zap,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const benefits = [
  {
    title: "No Vendor Lock-in",
    description:
      "Your voice data stays with you. No subscription to cancel, no service to shut down, no company to go out of business.",
    icon: Lock,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Transparent & Auditable",
    description:
      "Every line of code is visible. Security researchers and users can verify exactly what the software does.",
    icon: Eye,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Community Driven",
    description:
      "Built by Linux users, for Linux users. Features and fixes come from real users, not corporate roadmaps.",
    icon: Users,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Free Forever",
    description:
      "AGPL-3.0 licensed. Free to use, modify, and share. No freemium, no premium tier, no hidden costs.",
    icon: Heart,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
];

const vsProprietary = [
  { feature: "Cost", vocalinux: "Free forever", proprietary: "$10-500/month or $500+ license" },
  { feature: "Source Code", vocalinux: "Fully open", proprietary: "Closed, proprietary" },
  { feature: "Data Privacy", vocalinux: "Local engines by default", proprietary: "Often cloud-based" },
  { feature: "Linux Support", vocalinux: "Native", proprietary: "Limited or none" },
  { feature: "Customization", vocalinux: "Unlimited", proprietary: "Limited to vendor options" },
  { feature: "Vendor Dependency", vocalinux: "None", proprietary: "High" },
  { feature: "Community Support", vocalinux: "Active GitHub community", proprietary: "Paid support only" },
];

const techStack = [
  {
    name: "whisper.cpp",
    description: "High-performance C++ port of OpenAI's Whisper model",
    license: "MIT",
  },
  {
    name: "VOSK",
    description: "Offline speech recognition toolkit",
    license: "Apache 2.0",
  },
  {
    name: "GTK 3",
    description: "Cross-platform GUI toolkit for Linux",
    license: "LGPL",
  },
  {
    name: "Python",
    description: "Application logic and orchestration",
    license: "PSF License",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Open Source Voice Dictation for Linux | Vocalinux",
  description:
    "100% free and open source voice dictation for Linux. AGPL-3.0 licensed, no vendor lock-in, transparent code, community-driven development. Your voice data stays private.",
  path: "/open-source",
  keywords: [
    "open source voice dictation",
    "free speech to text Linux",
    "AGPL voice recognition",
    "FOSS dictation software",
    "Linux voice typing free",
    "transparent voice recognition",
    "community voice dictation",
    "no subscription dictation",
  ],
});

export default function OpenSourcePage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Open Source Voice Dictation for Linux",
    description:
      "Why Vocalinux is 100% open source. AGPL-3.0 licensed, community-driven, no vendor lock-in voice dictation for Linux.",
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
    mainEntityOfPage: absoluteUrl("/open-source"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-primary/10 px-4 py-1.5 text-sm font-medium text-muted-foreground">
          <Code className="h-4 w-4" />
          Open Source
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Free & Open Source Voice Dictation
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Vocalinux is 100% open source under the AGPL-3.0 license, and part of{" "}
          <a
            href="https://vocahq.com"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-primary hover:underline"
          >
            VocaHQ
          </a>
          . No subscriptions, no vendor lock-in, no hidden costs. Local engines keep
          audio on the machine. Remote API is optional.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-primary/5 p-6">
        <div className="mb-4 flex items-center gap-3">
          <Scale className="h-6 w-6 text-muted-foreground" />
          <h2 className="text-xl font-semibold text-foreground">
            AGPL-3.0 Licensed
          </h2>
        </div>
        <p className="mb-4 text-muted-foreground">
          Vocalinux is released under the GNU Affero General Public License v3.0, which means:
        </p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {[
            "Free to use for any purpose",
            "Free to study and modify",
            "Free to share with others",
            "Modifications must remain open",
            "Network-deployed modifications must offer source",
          ].map((item) => (
            <li key={item} className="flex items-center gap-2 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4" />
              {item}
            </li>
          ))}
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Why Open Source Matters</h2>
        <div className="grid gap-6 sm:grid-cols-2">
          {benefits.map((benefit) => {
            const Icon = benefit.icon;
            return (
              <article
                key={benefit.title}
                className="rounded-[12px] border border-border bg-background p-6"
              >
                <div className="mb-4 flex items-center gap-3">
                  <div className={`rounded-lg p-2.5 ${benefit.iconBg}`}>
                    <Icon className={`h-5 w-5 ${benefit.iconColor}`} />
                  </div>
                  <h3 className="font-semibold">{benefit.title}</h3>
                </div>
                <p className="text-sm text-muted-foreground">{benefit.description}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-6 font-display text-2xl font-semibold">Open Source vs Proprietary</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Feature</th>
                <th className="pb-3 pr-4 font-semibold">Vocalinux</th>
                <th className="pb-3 font-semibold">Proprietary Alternatives</th>
              </tr>
            </thead>
            <tbody>
              {vsProprietary.map((row) => (
                <tr key={row.feature} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{row.feature}</td>
                  <td className="py-3 pr-4 text-primary">{row.vocalinux}</td>
                  <td className="py-3 text-muted-foreground">{row.proprietary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Built on Open Source</h2>
        <p className="mb-6 text-muted-foreground">
          Vocalinux stands on the shoulders of these excellent open source projects:
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          {techStack.map((tech) => (
            <div
              key={tech.name}
              className="rounded-[12px] border border-border bg-background p-4"
            >
              <div className="mb-1 flex items-center justify-between">
                <h3 className="font-semibold">{tech.name}</h3>
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium bg-muted">
                  {tech.license}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">{tech.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <div className="flex items-start gap-4">
          <Shield className="mt-1 h-8 w-8 flex-shrink-0 text-primary" />
          <div>
            <h2 className="mb-3 text-xl font-semibold">Privacy by Design</h2>
            <p className="mb-4 text-muted-foreground">
              Because Vocalinux is open source, you can verify what local engines do on your
              machine. The installed app has no usage telemetry. Remote API is optional and only
              talks to a server you configure.
            </p>
            <div className="flex flex-wrap gap-2">
              {["No account required", "Local engines need no network after download", "No usage telemetry", "Full transparency"].map(
                (item) => (
                  <span
                    key={item}
                    className="rounded-full bg-muted px-3 py-1 text-xs font-medium bg-muted"
                  >
                    {item}
                  </span>
                )
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-primary/5 p-6">
        <div className="flex items-start gap-4">
          <GitBranch className="mt-1 h-6 w-6 flex-shrink-0 text-primary" />
          <div>
            <h3 className="mb-2 font-semibold text-foreground">
              Contribute to Vocalinux
            </h3>
            <p className="mb-4 text-sm text-muted-foreground">
              We welcome contributions! Whether it&apos;s bug fixes, features, documentation, or
              translations - join the community.
            </p>
            <a
              href="https://github.com/VocaHQ/vocalinux"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground hover:bg-muted"
            >
              <Zap className="h-4 w-4" />
              View on GitHub
            </a>
          </div>
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Join the Open Source Revolution</h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux and experience voice dictation that respects your freedom and privacy.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/install/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Install Free
            <ChevronRight className="h-4 w-4" />
          </Link>
          <Link
            href="/alternatives/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted hover:bg-muted"
          >
            Compare Alternatives
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
