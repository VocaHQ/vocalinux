import Link from "next/link";
import { type Metadata } from "next";
import { Accessibility, BookOpen, Briefcase, ChevronRight, Code, Feather, GraduationCap, Heart, Users } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const useCases = [
  {
    title: "Developers",
    icon: Code,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    description: "Code faster with voice. Dictate comments, documentation, and even code snippets hands-free.",
    benefits: [
      "Dictate code comments while keeping hands on the keyboard",
      "Write documentation at the speed of thought",
      "Reduce RSI from constant typing",
      "Multitask: review code while dictating notes",
    ],
    commands: ["new line", "open parenthesis", "close parenthesis", "tab"],
  },
  {
    title: "Writers & Authors",
    icon: Feather,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    description: "Capture ideas as fast as you can think them. Perfect for drafts, articles, and creative writing.",
    benefits: [
      "Write at natural speaking speed (100+ WPM)",
      "Overcome writer's block by speaking freely",
      "Maintain creative flow without keyboard interruptions",
      "Dictate while walking or pacing",
    ],
    commands: ["new paragraph", "quote", "delete that", "undo"],
  },
  {
    title: "Students",
    icon: GraduationCap,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    description: "Take notes during lectures, transcribe recordings, and write essays faster.",
    benefits: [
      "Take lecture notes at speaking speed",
      "Transcribe audio recordings for study",
      "Write essays and papers hands-free",
      "Multi-language support for language learners",
    ],
    commands: ["select all", "copy", "paste", "new line"],
  },
  {
    title: "Accessibility Users",
    icon: Accessibility,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    description: "Full voice control for users with mobility impairments, RSI, or carpal tunnel.",
    benefits: [
      "Type without using hands",
      "Reduce strain from repetitive typing",
      "Independence for users with physical disabilities",
      "Local engines, no required cloud account",
    ],
    commands: ["select all", "delete that", "undo", "redo"],
  },
  {
    title: "Professionals",
    icon: Briefcase,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    description: "Dictate emails, reports, and meeting notes. Boost productivity in any profession.",
    benefits: [
      "Draft emails quickly with natural speech",
      "Create meeting minutes in real-time",
      "Write reports hands-free",
      "Local engines keep audio on the machine",
    ],
    commands: ["new paragraph", "comma", "period", "send"],
  },
  {
    title: "Content Creators",
    icon: Heart,
    iconColor: "text-primary",
    iconBg: "bg-primary/10",
    description: "Create YouTube scripts, podcast notes, and social media content at speaking speed.",
    benefits: [
      "Write scripts as fast as you can speak",
      "Transcribe video/audio content",
      "Draft social media posts hands-free",
      "Create captions and subtitles",
    ],
    commands: ["new line", "quote", "colon", "hashtag"],
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Use Cases - Who Uses Vocalinux Voice Dictation",
  description:
    "Discover how developers, writers, students, and professionals use Vocalinux for Linux voice dictation. Find your use case and boost productivity.",
  path: "/use-cases",
  keywords: [
    "voice dictation for developers",
    "speech to text for writers",
    "linux accessibility voice typing",
    "dictation software for students",
  ],
});

export default function UseCasesPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Vocalinux Use Cases - Voice Dictation for Every Workflow",
    description:
      "Discover how different professionals use Vocalinux for Linux voice dictation.",
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
    mainEntityOfPage: absoluteUrl("/use-cases"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Users className="h-4 w-4" />
          For Everyone
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Voice Dictation for Every Workflow
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Whether you're coding, writing, studying, or need accessibility support, Vocalinux adapts
          to your needs. See how different professionals use voice dictation to boost productivity.
        </p>
      </section>

      <section className="space-y-8">
        {useCases.map((useCase) => {
          const Icon = useCase.icon;
          return (
            <article
              key={useCase.title}
              className="rounded-[12px] border border-border bg-background p-6"
            >
              <div className="mb-6 flex flex-wrap items-start gap-4">
                <div className={`rounded-[12px] p-3 ${useCase.iconBg}`}>
                  <Icon className={`h-6 w-6 ${useCase.iconColor}`} />
                </div>
                <div className="flex-1">
                  <h2 className="mb-2 font-display text-2xl font-semibold">{useCase.title}</h2>
                  <p className="text-muted-foreground">{useCase.description}</p>
                </div>
              </div>

              <div className="grid gap-6 md:grid-cols-2">
                <div>
                  <h3 className="mb-3 font-semibold">Key Benefits</h3>
                  <ul className="space-y-2">
                    {useCase.benefits.map((benefit) => (
                      <li key={benefit} className="flex items-start gap-2 text-sm text-muted-foreground">
                        <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                        {benefit}
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <h3 className="mb-3 font-semibold">Helpful Voice Commands</h3>
                  <div className="flex flex-wrap gap-2">
                    {useCase.commands.map((cmd) => (
                      <kbd
                        key={cmd}
                        className="rounded-lg border border-border bg-muted px-2 py-1 text-xs font-mono"
                      >
                        "{cmd}"
                      </kbd>
                    ))}
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </section>

      <section className="mt-12 rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Ready to Get Started?</h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux in minutes and start dictating in any application on Linux.
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
            href="/shortcuts/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted hover:bg-muted"
          >
            View Voice Commands
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
