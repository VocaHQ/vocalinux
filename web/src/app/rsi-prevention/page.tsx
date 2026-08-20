import Link from "next/link";
import { type Metadata } from "next";
import { CheckCircle2, ChevronRight, Heart, Keyboard, Shield, User } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const benefits = [
  {
    title: "Reduce Physical Strain",
    description:
      "Give your hands, wrists, and fingers a break. Voice dictation lets you type without the physical toll of keyboard use.",
    icon: Heart,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Prevent Repetitive Stress",
    description:
      "RSI develops from thousands of repeated motions. Dictating breaks the cycle and allows recovery.",
    icon: Keyboard,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Privacy for Health",
    description:
      "Local engines process speech on your machine. Remote API is optional and only talks to a server you configure.",
    icon: Shield,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
  {
    title: "Independence",
    description:
      "For those with mobility limitations, voice dictation provides computer independence without relying on others.",
    icon: User,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
  },
];

const conditions = [
  {
    name: "Carpal Tunnel Syndrome",
    description:
      "Compression of the median nerve causing numbness, tingling, and weakness in the hand.",
    howDictationHelps:
      "Eliminate the wrist movements that aggravate symptoms while maintaining productivity.",
  },
  {
    name: "Repetitive Strain Injury (RSI)",
    description: "Pain in muscles, nerves, or tendons caused by repetitive movements and overuse.",
    howDictationHelps:
      "Break the cycle of repetitive keystrokes and allow your hands to recover.",
  },
  {
    name: "Tendinitis",
    description: "Inflammation or irritation of a tendon, often affecting the wrist and fingers.",
    howDictationHelps:
      "Reduce tendon stress by speaking instead of typing for extended periods.",
  },
  {
    name: "Tennis Elbow (Lateral Epicondylitis)",
    description: "Overuse injury causing pain on the outside of the elbow and forearm.",
    howDictationHelps:
      "Minimize the gripping and wrist motions that exacerbate elbow pain.",
  },
  {
    name: "Thoracic Outlet Syndrome",
    description:
      "Compression of nerves or blood vessels in the lower neck and upper chest.",
    howDictationHelps:
      "Reduce the forward-head posture and shoulder tension common with keyboard use.",
  },
  {
    name: "General Mobility Limitations",
    description:
      "Conditions affecting hand, arm, or finger movement from various causes.",
    howDictationHelps:
      "Full computer control without physical keyboard interaction required.",
  },
];

const statistics = [
  { value: "8+", label: "Hours per day average computer use for office workers" },
  { value: "50%", label: "Of computer users experience RSI symptoms" },
  { value: "100+", label: "Words per minute achievable with voice dictation" },
  { value: "Local", label: "Engines run on your machine unless you enable Remote API" },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Voice Dictation for RSI & Carpal Tunnel Prevention | Vocalinux",
  description:
    "Prevent and manage RSI, carpal tunnel, and repetitive strain injuries with voice dictation. Hands-free typing for Linux users with local engines or an optional Remote API.",
  path: "/rsi-prevention",
  keywords: [
    "RSI voice dictation",
    "carpal tunnel voice typing",
    "hands-free typing",
    "repetitive strain injury prevention",
    "voice typing for wrist pain",
    "dictation software for RSI",
    "ergonomic typing alternative",
    "Linux voice dictation accessibility",
  ],
});

export default function RsiPreventionPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Voice Dictation for RSI & Carpal Tunnel Prevention",
    description:
      "How voice dictation helps prevent and manage repetitive strain injuries. Hands-free typing solution for Linux users.",
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
    mainEntityOfPage: absoluteUrl("/rsi-prevention"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-primary/10 px-4 py-1.5 text-sm font-medium text-primary">
          <Heart className="h-4 w-4" />
          Health & Accessibility
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Voice Dictation for RSI Prevention
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Suffering from carpal tunnel, wrist pain, or repetitive strain? Voice dictation lets you
          keep working without the physical toll. Local engines run on your Linux machine. Remote
          API is optional.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statistics.map((stat) => (
          <div
            key={stat.label}
            className="rounded-[12px] border border-border bg-background p-5 text-center"
          >
            <p className="mb-1 font-display text-3xl font-semibold text-primary">{stat.value}</p>
            <p className="text-sm text-muted-foreground">{stat.label}</p>
          </div>
        ))}
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Why Voice Dictation Helps</h2>
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

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Conditions Helped by Voice Dictation</h2>
        <div className="space-y-4">
          {conditions.map((condition) => (
            <article
              key={condition.name}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 font-semibold">{condition.name}</h3>
              <p className="mb-3 text-sm text-muted-foreground">{condition.description}</p>
              <div className="rounded-lg bg-primary/10 p-3 dark:bg-primary/10">
                <p className="text-sm text-primary dark:text-[color:var(--terminal-fg)]">
                  <strong>How dictation helps:</strong> {condition.howDictationHelps}
                </p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">Getting Started with Hands-Free Typing</h2>
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="mb-3 font-semibold">Tips for Transitioning</h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Start by dictating emails and documents, then expand to other tasks
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Use voice commands for punctuation to maintain natural speech flow
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Take breaks - voice dictation is still work, and vocal rest matters too
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Combine with ergonomic equipment for maximum benefit
              </li>
            </ul>
          </div>
          <div>
            <h3 className="mb-3 font-semibold">Vocalinux Advantages</h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Toggle mode or push-to-talk control - no mouse required
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                System tray indicator shows recording status
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Pleasant audio feedback confirms start/stop
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Works in ALL Linux applications - universal compatibility
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-primary/10 p-8 dark:border-border">
        <h2 className="mb-4 font-display text-2xl font-semibold text-primary">
          Take Care of Your Hands
        </h2>
        <p className="mb-6 text-primary">
          Your health matters. If you&apos;re experiencing pain, numbness, or tingling, consult a
          healthcare professional. Voice dictation is a tool to help, not a substitute for proper
          medical care.
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
            href="/use-cases/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/10 dark:bg-primary/10 dark:hover:bg-primary/10"
          >
            See Other Use Cases
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
