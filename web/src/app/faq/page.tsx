import Link from "next/link";
import { type Metadata } from "next";
import {
  BookOpen,
  ChevronRight,
  CircleHelp,
  Cpu,
  Laptop,
  Lock,
  Mic,
  Volume2,
  Zap,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { buildPageMetadata } from "@/lib/seo";

const faqCategories = [
  {
    category: "Getting Started",
    icon: Zap,
    iconColor: "text-primary",
    questions: [
      {
        q: "How do I install Vocalinux?",
        a: "Run the one-liner installer: curl -fsSL https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/install.sh | bash. The installer handles dependencies and configuration. You can also download an AppImage from GitHub Releases if you prefer a no-root portable binary (host xdotool/wtype/ydotool still required for text injection).",
      },
      {
        q: "Which Linux distributions are supported?",
        a: "Vocalinux works on Ubuntu 22.04+, Fedora 39+, Arch Linux, Manjaro, Debian, and most other Linux distributions. See our install guides for distro-specific instructions.",
      },
      {
        q: "What are the system requirements?",
        a: "You need Python 3.9+, a working microphone, and about 500MB of disk space. For GPU acceleration with whisper.cpp, you need Vulkan support (AMD, Intel, or NVIDIA).",
      },
    ],
  },
  {
    category: "Privacy & Security",
    icon: Lock,
    iconColor: "text-primary",
    questions: [
      {
        q: "Is Vocalinux really 100% offline?",
        a: "Yes for local engines. whisper.cpp, Whisper, and VOSK run on your Linux machine. Vocalinux also offers an optional Remote API engine for servers you configure yourself.",
      },
      {
        q: "Does Vocalinux send any data to external servers?",
        a: "Local engines do not send voice data externally. Remote API mode sends audio only to the transcription server URL you configure.",
      },
      {
        q: "Is my voice data stored anywhere?",
        a: "Only temporarily during transcription. Audio is processed in real-time and discarded immediately. No voice recordings are saved to disk.",
      },
    ],
  },
  {
    category: "Speech Recognition",
    icon: Mic,
    iconColor: "text-primary",
    questions: [
      {
        q: "Which speech recognition engines are available?",
        a: "Vocalinux supports whisper.cpp (default), OpenAI Whisper, VOSK, and Remote API for compatible self-hosted or trusted transcription servers.",
      },
      {
        q: "How accurate is the transcription?",
        a: "Accuracy depends on the engine and model size. whisper.cpp with medium or large models provides excellent accuracy for English and 99+ other languages.",
      },
      {
        q: "Can I use Vocalinux in languages other than English?",
        a: "Yes! whisper.cpp and Whisper support 99+ languages with automatic language detection. VOSK supports several languages with separate models.",
      },
      {
        q: "What is Silero VAD?",
        a: "Silero VAD is neural voice activity detection. Vocalinux uses it when ONNX Runtime support is available to drop silence-only buffers before recognition.",
      },
    ],
  },
  {
    category: "Usage & Features",
    icon: Volume2,
    iconColor: "text-primary",
    questions: [
      {
        q: "How do I start and stop dictation?",
        a: "By default, hold Right Alt (Option on Mac-layout keyboards) to speak and release to stop (push-to-talk). You can switch to toggle mode (double-tap a key to start/stop) or change the key in Settings.",
      },
      {
        q: "Does Vocalinux work with Wayland?",
        a: "Yes. Vocalinux supports both X11 and Wayland, including IBus-based flows on Wayland with improved active-method detection for more reliable text injection.",
      },
      {
        q: "What happens when I close my laptop lid?",
        a: "Vocalinux v0.10.1+ automatically recovers speech recognition after system suspend/resume. The app detects when your system wakes up and restarts the recognition engine and keyboard shortcuts. No manual restart needed - just start dictating as usual.",
      },
      {
        q: "Does Vocalinux preserve my keyboard layout?",
        a: "Yes! v0.10.1+ preserves your XKB keyboard layout when activating IBus for text injection. Unlike other tools that switch to US layout, Vocalinux keeps your configured layout so you can dictate without unexpected character changes.",
      },
      {
        q: "Can I use voice commands?",
        a: "Yes. Vocalinux supports commands like 'new line', 'delete that', 'select all', and more. Voice commands are optional and can be enabled or disabled in Settings.",
      },
    ],
  },
  {
    category: "Performance",
    icon: Cpu,
    iconColor: "text-primary",
    questions: [
      {
        q: "How much RAM does Vocalinux need?",
        a: "Minimum 4GB RAM for basic use. For larger models, 8GB+ recommended. VOSK is the most memory-efficient option for systems with limited RAM.",
      },
      {
        q: "Can I use GPU acceleration?",
        a: "Yes. whisper.cpp supports GPU acceleration via Vulkan on AMD, Intel, and NVIDIA. On multi-GPU machines Vocalinux prefers a discrete device when possible; you can pick a device under Advanced settings.",
      },
      {
        q: "What model size should I use?",
        a: "Start with 'tiny' for fastest performance, 'base' or 'small' for good balance, or 'medium'/'large' for best accuracy. Larger models need more RAM.",
      },
    ],
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Frequently Asked Questions - Vocalinux Voice Dictation",
  description:
    "Get answers to common questions about Vocalinux Linux voice dictation. Learn about installation, privacy, features, and troubleshooting.",
  path: "/faq",
  keywords: [
    "vocalinux faq",
    "linux voice dictation help",
    "speech to text linux questions",
    "offline dictation faq",
  ],
});

export default function FaqPage() {
  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    dateModified: "2026-06-11",
    mainEntity: faqCategories.flatMap((cat) =>
      cat.questions.map((q) => ({
        "@type": "Question",
        name: q.q,
        acceptedAnswer: {
          "@type": "Answer",
          text: q.a,
        },
      })),
    ),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />

      <section>
        <p className="border-primary/30 bg-primary/10 mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium text-primary">
          <CircleHelp className="h-4 w-4" />
          Help Center
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Frequently Asked Questions
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Find answers to common questions about Vocalinux. From installation to
          advanced features, we've got you covered.
        </p>
      </section>

      <section className="space-y-8">
        {faqCategories.map((category) => {
          const Icon = category.icon;
          return (
            <article
              key={category.category}
              className="rounded-[12px] border border-border bg-background p-6"
            >
              <h2 className="mb-6 flex items-center gap-3 font-display text-2xl font-semibold">
                <span className={`rounded-[12px] bg-muted p-2 bg-muted`}>
                  <Icon className={`h-5 w-5 ${category.iconColor}`} />
                </span>
                {category.category}
              </h2>

              <div className="space-y-6">
                {category.questions.map((item, index) => (
                  <div
                    key={index}
                    className="border-b border-border pb-6 last:border-0 last:pb-0"
                  >
                    <h3 className="mb-2 text-lg font-semibold">{item.q}</h3>
                    <p className="text-muted-foreground">{item.a}</p>
                  </div>
                ))}
              </div>
            </article>
          );
        })}
      </section>

      <section className="mt-12 rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Still have questions?</h2>
        <ul className="space-y-3 text-muted-foreground">
          <li>
            <span className="inline-flex items-center gap-2">
              <Laptop className="h-4 w-4 text-primary" />
              Check the{" "}
              <Link
                href="/install/"
                className="font-semibold text-primary hover:underline"
              >
                install guide
              </Link>{" "}
              for setup help
            </span>
          </li>
          <li>
            <span className="inline-flex items-center gap-2">
              <BookOpen className="h-4 w-4 text-primary" />
              See the{" "}
              <Link
                href="/troubleshooting/"
                className="font-semibold text-primary hover:underline"
              >
                troubleshooting guide
              </Link>{" "}
              for common issues
            </span>
          </li>
          <li>
            <span className="inline-flex items-center gap-2">
              <ChevronRight className="h-4 w-4 text-primary" />
              <a
                href="https://github.com/jatinkrmalik/vocalinux/issues"
                target="_blank"
                rel="noopener noreferrer"
                className="font-semibold text-primary hover:underline"
              >
                Open an issue on GitHub
              </a>
            </span>
          </li>
        </ul>
      </section>
    </SeoSubpageShell>
  );
}
