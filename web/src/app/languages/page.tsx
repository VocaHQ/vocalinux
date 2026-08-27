import Link from "next/link";
import { type Metadata } from "next";
import { CheckCircle2, ChevronRight, Globe, Languages, Mic } from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const WHISPER_ENGINES = ["whisper.cpp", "Whisper"] as const;
const ALL_ENGINES = ["whisper.cpp", "Whisper", "VOSK"] as const;

const supportedLanguages = [
  {
    code: "en",
    name: "English",
    nativeName: "English",
    flag: "🇺🇸",
    description: "Full support across all engines (whisper.cpp, Whisper, VOSK)",
    engines: [...ALL_ENGINES],
  },
  {
    code: "en-in",
    name: "English (India)",
    nativeName: "English (India)",
    flag: "🇮🇳",
    description: "Indian English dictation with a dedicated VOSK model",
    engines: [...ALL_ENGINES],
  },
  {
    code: "ar",
    name: "Arabic",
    nativeName: "العربية",
    flag: "🇸🇦",
    description: "Arabic speech recognition across Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "bn",
    name: "Bengali",
    nativeName: "বাংলা",
    flag: "🇧🇩",
    description: "Bengali dictation with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "ca",
    name: "Catalan",
    nativeName: "Català",
    flag: "🇦🇩",
    description: "Catalan voice typing with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "zh",
    name: "Chinese",
    nativeName: "中文",
    flag: "🇨🇳",
    description: "Mandarin Chinese voice dictation support",
    engines: [...ALL_ENGINES],
  },
  {
    code: "cs",
    name: "Czech",
    nativeName: "Čeština",
    flag: "🇨🇿",
    description: "Czech dictation with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "da",
    name: "Danish",
    nativeName: "Dansk",
    flag: "🇩🇰",
    description: "Danish speech-to-text with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "nl",
    name: "Dutch",
    nativeName: "Nederlands",
    flag: "🇳🇱",
    description: "Dutch voice recognition across Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "fi",
    name: "Finnish",
    nativeName: "Suomi",
    flag: "🇫🇮",
    description: "Finnish dictation with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "fr",
    name: "French",
    nativeName: "Français",
    flag: "🇫🇷",
    description: "French language voice typing and transcription",
    engines: [...ALL_ENGINES],
  },
  {
    code: "de",
    name: "German",
    nativeName: "Deutsch",
    flag: "🇩🇪",
    description: "German dictation with high accuracy",
    engines: [...ALL_ENGINES],
  },
  {
    code: "el",
    name: "Greek",
    nativeName: "Ελληνικά",
    flag: "🇬🇷",
    description: "Greek speech recognition with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "he",
    name: "Hebrew",
    nativeName: "עברית",
    flag: "🇮🇱",
    description: "Hebrew dictation with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "hi",
    name: "Hindi",
    nativeName: "हिन्दी",
    flag: "🇮🇳",
    description: "Hindi language voice typing and transcription",
    engines: [...ALL_ENGINES],
  },
  {
    code: "hu",
    name: "Hungarian",
    nativeName: "Magyar",
    flag: "🇭🇺",
    description: "Hungarian dictation with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "id",
    name: "Indonesian",
    nativeName: "Bahasa Indonesia",
    flag: "🇮🇩",
    description: "Indonesian voice typing with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "it",
    name: "Italian",
    nativeName: "Italiano",
    flag: "🇮🇹",
    description: "Italian voice recognition and text dictation",
    engines: [...ALL_ENGINES],
  },
  {
    code: "ja",
    name: "Japanese",
    nativeName: "日本語",
    flag: "🇯🇵",
    description: "Japanese speech-to-text across Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "ko",
    name: "Korean",
    nativeName: "한국어",
    flag: "🇰🇷",
    description: "Korean dictation with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "no",
    name: "Norwegian",
    nativeName: "Norsk",
    flag: "🇳🇴",
    description: "Norwegian speech recognition with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "fa",
    name: "Persian",
    nativeName: "فارسی",
    flag: "🇮🇷",
    description: "Persian (Farsi) dictation with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "pl",
    name: "Polish",
    nativeName: "Polski",
    flag: "🇵🇱",
    description: "Polish voice typing with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "pt",
    name: "Portuguese",
    nativeName: "Português",
    flag: "🇧🇷",
    description: "Brazilian and European Portuguese support",
    engines: [...ALL_ENGINES],
  },
  {
    code: "ro",
    name: "Romanian",
    nativeName: "Română",
    flag: "🇷🇴",
    description: "Romanian dictation with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "ru",
    name: "Russian",
    nativeName: "Русский",
    flag: "🇷🇺",
    description: "Russian language speech-to-text transcription",
    engines: [...ALL_ENGINES],
  },
  {
    code: "es",
    name: "Spanish",
    nativeName: "Español",
    flag: "🇪🇸",
    description: "Complete Spanish language support for dictation",
    engines: [...ALL_ENGINES],
  },
  {
    code: "sv",
    name: "Swedish",
    nativeName: "Svenska",
    flag: "🇸🇪",
    description: "Swedish voice recognition with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "ta",
    name: "Tamil",
    nativeName: "தமிழ்",
    flag: "🇮🇳",
    description: "Tamil dictation with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "th",
    name: "Thai",
    nativeName: "ไทย",
    flag: "🇹🇭",
    description: "Thai speech-to-text with multilingual Whisper models",
    engines: [...WHISPER_ENGINES],
  },
  {
    code: "tr",
    name: "Turkish",
    nativeName: "Türkçe",
    flag: "🇹🇷",
    description: "Turkish dictation with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "uk",
    name: "Ukrainian",
    nativeName: "Українська",
    flag: "🇺🇦",
    description: "Ukrainian voice typing with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
  {
    code: "vi",
    name: "Vietnamese",
    nativeName: "Tiếng Việt",
    flag: "🇻🇳",
    description: "Vietnamese speech recognition with Whisper and VOSK",
    engines: [...ALL_ENGINES],
  },
];

const languageCount = supportedLanguages.length;

const features = [
  {
    title: "Automatic Language Detection",
    description:
      "Vocalinux can automatically detect the language you're speaking, no manual switching required.",
    icon: Globe,
  },
  {
    title: "Engine-Aware Catalog",
    description:
      "Whisper engines cover the full language list. VOSK appears only where an official model exists.",
    icon: Mic,
  },
  {
    title: "Offline Processing",
    description:
      "Local engines process each language on your machine. Remote API is optional.",
    icon: CheckCircle2,
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Multilingual Voice Dictation - 30+ Languages | Vocalinux",
  description:
    "Dictate in 30+ languages including Spanish, French, German, Hungarian, Japanese, Korean, Arabic, and more. Free offline multilingual voice typing for Linux.",
  path: "/languages",
  keywords: [
    "multilingual voice dictation",
    "Spanish voice typing",
    "French speech to text",
    "German dictation software",
    "Hungarian voice recognition",
    "Japanese speech to text",
    "Korean voice typing",
    "Arabic dictation",
    "Italian voice recognition",
    "Portuguese voice typing",
    "Russian speech recognition",
    "Chinese dictation",
    "Hindi voice typing",
    "Linux multilingual dictation",
  ],
});

export default function LanguagesPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: `Multilingual Voice Dictation for Linux - ${languageCount}+ Languages Supported`,
    description:
      "Complete guide to Vocalinux multilingual voice dictation. Dictate in Spanish, French, German, Hungarian, Japanese, Korean, Arabic, Hindi, and more.",
    dateModified: "2026-07-29",
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
    mainEntityOfPage: absoluteUrl("/languages"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Languages className="h-4 w-4" />
          {languageCount}+ Languages
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Multilingual Voice Dictation for Linux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Dictate in your native language. Vocalinux lists {languageCount} languages in Settings,
          and whisper.cpp / Whisper can auto-detect many more. Local engines stay on the machine.
        </p>
      </section>

      <section className="mb-12 grid gap-6 sm:grid-cols-3">
        {features.map((feature) => {
          const Icon = feature.icon;
          return (
            <div
              key={feature.title}
              className="rounded-[12px] border border-border bg-background p-6"
            >
              <Icon className="mb-3 h-8 w-8 text-primary" />
              <h3 className="mb-2 font-semibold">{feature.title}</h3>
              <p className="text-sm text-muted-foreground">{feature.description}</p>
            </div>
          );
        })}
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">Supported Languages</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {supportedLanguages.map((lang) => (
            <article
              key={lang.code}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <div className="mb-3 flex items-center gap-3">
                <span className="text-3xl">{lang.flag}</span>
                <div>
                  <h3 className="font-semibold">{lang.name}</h3>
                  <p className="text-sm text-muted-foreground">{lang.nativeName}</p>
                </div>
              </div>
              <p className="mb-3 text-sm text-muted-foreground">{lang.description}</p>
              <div className="flex flex-wrap gap-1">
                {lang.engines.map((engine) => (
                  <span
                    key={engine}
                    className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium bg-muted"
                  >
                    {engine}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">How Language Support Works</h2>
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="mb-3 font-semibold">Language Selection</h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Select your language in Settings → Speech Engine → Language
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Use &quot;Auto&quot; for automatic language detection (whisper.cpp/Whisper)
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Switch languages on-the-fly without restarting
              </li>
            </ul>
          </div>
          <div>
            <h3 className="mb-3 font-semibold">Model Selection</h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Larger models provide better accuracy for all languages
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Use a Standard multilingual whisper.cpp model for non-English dictation
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                Models are downloaded automatically on first use
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">Ready to Dictate in Your Language?</h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux and start dictating in your preferred language. All processing happens
          locally on your Linux machine.
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
