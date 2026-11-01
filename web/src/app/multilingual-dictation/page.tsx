import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Globe,
  Keyboard,
  Languages,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/multilingual-dictation";

// Mirrors SUPPORTED_LANGUAGES in src/vocalinux/utils/vosk_model_info.py (v0.18.5).
const catalog: { code: string; name: string; vosk: boolean }[] = [
  { code: "en-us", name: "English (US)", vosk: true },
  { code: "en-in", name: "English (India)", vosk: true },
  { code: "ar", name: "Arabic", vosk: true },
  { code: "bn", name: "Bengali", vosk: false },
  { code: "ca", name: "Catalan", vosk: true },
  { code: "zh", name: "Chinese", vosk: true },
  { code: "cs", name: "Czech", vosk: true },
  { code: "da", name: "Danish", vosk: false },
  { code: "nl", name: "Dutch", vosk: true },
  { code: "fi", name: "Finnish", vosk: false },
  { code: "fr", name: "French", vosk: true },
  { code: "de", name: "German", vosk: true },
  { code: "el", name: "Greek", vosk: false },
  { code: "he", name: "Hebrew", vosk: false },
  { code: "hi", name: "Hindi", vosk: true },
  { code: "hu", name: "Hungarian", vosk: false },
  { code: "id", name: "Indonesian", vosk: false },
  { code: "it", name: "Italian", vosk: true },
  { code: "ja", name: "Japanese", vosk: true },
  { code: "ko", name: "Korean", vosk: true },
  { code: "no", name: "Norwegian", vosk: false },
  { code: "fa", name: "Persian", vosk: true },
  { code: "pl", name: "Polish", vosk: true },
  { code: "pt", name: "Portuguese", vosk: true },
  { code: "ro", name: "Romanian", vosk: false },
  { code: "ru", name: "Russian", vosk: true },
  { code: "sl", name: "Slovenian", vosk: false },
  { code: "es", name: "Spanish", vosk: true },
  { code: "sv", name: "Swedish", vosk: true },
  { code: "ta", name: "Tamil", vosk: false },
  { code: "th", name: "Thai", vosk: false },
  { code: "tr", name: "Turkish", vosk: true },
  { code: "uk", name: "Ukrainian", vosk: true },
  { code: "vi", name: "Vietnamese", vosk: true },
];

const engineRows = [
  {
    engine: "whisper.cpp (default)",
    picker: "Full catalog",
    layout: "Yes",
    shortcuts: "Yes",
    note: "Needs a multilingual model, not a .en one. Also offers Language Candidates.",
  },
  {
    engine: "Whisper, Faster Whisper",
    picker: "Full catalog",
    layout: "Yes",
    shortcuts: "Yes",
    note: "Needs a multilingual model.",
  },
  {
    engine: "Remote API",
    picker: "Full catalog",
    layout: "Yes",
    shortcuts: "Yes",
    note: "The language is sent with each request to the server you configured.",
  },
  {
    engine: "VOSK",
    picker: "Languages with an official model",
    layout: "No",
    shortcuts: "No",
    note: "One model per language, so switching means a model reload.",
  },
  {
    engine: "Parakeet",
    picker: "Not used",
    layout: "No",
    shortcuts: "No",
    note: "Language comes from the model: v3-european or v2-english.",
  },
];

const howToSteps = [
  {
    name: "Use a multilingual model",
    text: "In Settings → Speech Model, pick a language other than English or a multilingual model. English-only models, the ones with .en in the name, cannot switch language.",
  },
  {
    name: "Add a language shortcut",
    text: "Open Settings → Dictation, find Language Shortcuts and click Add Language Shortcut.",
  },
  {
    name: "Pick the language and record a key",
    text: "Choose the language in the new row, click Record and press a modifier plus a key such as ctrl+alt+d, or a function key such as f10.",
  },
  {
    name: "Dictate with it",
    text: "Press the language shortcut instead of your main one. It follows the shortcut mode above it, so hold it for push-to-talk or press it to toggle. Your main language comes back after that dictation.",
  },
];

const faqs = [
  {
    q: "How many languages does Vocalinux support?",
    a: "The language catalog has 33 languages plus Auto-detect. English appears twice, as English (US) and English (India), so the list has 34 entries. Slovenian was added in v0.18.4.",
  },
  {
    q: "Can Vocalinux switch language in the middle of a sentence?",
    a: "No. Whisper-family engines take one language per dictation, or detect it once per utterance on Auto-detect. For mixed-language work, use Follow keyboard layout or a language shortcut so each dictation starts in the right language.",
  },
  {
    q: "Follow keyboard layout always picks the same language. Why?",
    a: "Reading the active layout uses GNOME's input-source settings. On other desktops Vocalinux falls back to the configured primary layout, which does not change when you switch. A layout that maps to no catalog language falls back to auto-detect.",
  },
  {
    q: "My language shortcut plays an error sound. What is wrong?",
    a: "The loaded model cannot dictate in that language without a reload: an English-only Whisper model, a VOSK model for another language, or Parakeet. Vocalinux refuses rather than dictating in the wrong language. Choose a multilingual Whisper-family model.",
  },
  {
    q: "Do voice commands work in other languages?",
    a: "Punctuation and line-break phrases also match in Italian, French, German, Spanish, Portuguese, Dutch, Polish and Russian. Editing commands such as delete that and undo are English-only.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Multilingual Voice Dictation on Linux: 33 Languages | Vocalinux",
  description:
    "Dictate in more than one language on Linux: per-language shortcuts, follow your keyboard layout, 33 languages plus auto-detect, and per-engine limits.",
  path: PAGE_PATH,
  keywords: [
    "multilingual dictation Linux",
    "bilingual voice typing Linux",
    "switch dictation language shortcut",
    "follow keyboard layout dictation",
    "Whisper multilingual dictation",
    "offline speech to text languages Linux",
  ],
});

export default function MultilingualDictationPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Multilingual Voice Dictation on Linux with Vocalinux",
    description:
      "How to dictate in more than one language with Vocalinux: the language catalog, per-language shortcuts, following the keyboard layout and engine caveats.",
    dateModified: "2026-11-01",
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
    mainEntityOfPage: absoluteUrl(PAGE_PATH),
  };

  const howToJsonLd = {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: "Set up a per-language dictation shortcut in Vocalinux",
    step: howToSteps.map((step, index) => ({
      "@type": "HowToStep",
      position: index + 1,
      name: step.name,
      text: step.text,
    })),
  };

  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(howToJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />

      <section>
        <p className="subpage-kicker">Added in v0.18.0</p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Multilingual dictation on Linux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Per-language shortcuts and Follow keyboard layout arrived in v0.18.0.
          If you write in more than one language, Vocalinux gives you three ways
          to get the right one each time: auto-detect per utterance, a separate
          shortcut per language, or following whichever keyboard layout you are
          typing with. This page covers each, which engines support them, and
          where they fall short. For a per-language view of engine support, see
          the <Link href="/languages/">languages page</Link>.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-3">
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Globe className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Auto-detect</h3>
          <p className="text-sm text-muted-foreground">
            The engine guesses the language for each utterance. Easiest to set
            up, but short clips can be guessed wrong.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Keyboard className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Language shortcuts</h3>
          <p className="text-sm text-muted-foreground">
            A dedicated key per language. Explicit and reliable, for one
            dictation at a time.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Languages className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <h3 className="mb-2 font-semibold">Follow keyboard layout</h3>
          <p className="text-sm text-muted-foreground">
            Switch layout to switch dictation language. Best on GNOME, where the
            active layout can be read.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Choosing a main language
        </h2>
        <p className="mb-4 text-muted-foreground">
          Settings → Speech Model opens with a simple Language group. Pick your
          Main language from the searchable list. Turning on Other languages
          makes the engine guess the language each time; the optional Other
          language picker just records which one you had in mind, because
          Whisper-family engines take a single language or none. On first run,
          Vocalinux seeds the language from your keyboard layout and locale
          (since v0.17.0).
        </p>
        <p className="text-muted-foreground">
          Picking a language other than English switches off an English-only
          model. From the command line, <code>--language</code> accepts{" "}
          <code>auto</code> or any catalog code below.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Per-language dictation shortcuts
        </h2>
        <ol className="space-y-4">
          {howToSteps.map((step, index) => (
            <li
              key={step.name}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <div className="mb-2 flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {index + 1}
                </span>
                <h3 className="font-semibold">{step.name}</h3>
              </div>
              <p className="ml-10 text-sm text-muted-foreground">{step.text}</p>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-sm text-muted-foreground">
          Bindings take effect immediately. A binding can also point at
          Auto-detect. If two rows use the same key, the first one wins. More on
          shortcut syntax and modes is on the{" "}
          <Link href="/shortcuts/">shortcuts page</Link>.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Following the keyboard layout
        </h2>
        <p className="mb-4 text-muted-foreground">
          Expand Advanced on the Speech Model page and turn on Follow keyboard
          layout. Vocalinux then re-reads the active layout at the start of
          every dictation and uses the matching language. The Language picker
          greys out and shows what the current layout resolves to; turning the
          switch off pins that language.
        </p>
        <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            Available for whisper.cpp, Whisper and Faster Whisper with a
            multilingual model, and for the Remote API.
          </li>
          <li>
            The active layout is read from GNOME&apos;s input-source settings.
            Some IBus input methods map too, for example Mozc and Anthy to
            Japanese, Pinyin and Rime to Chinese, and Hangul to Korean.
          </li>
          <li>
            On other desktops Vocalinux uses the configured primary layout,
            which does not follow your switches. A layout with no catalog
            language falls back to auto-detect.
          </li>
          <li>
            A language shortcut wins over the layout for that one dictation.
          </li>
        </ul>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          The settings in config.json
        </h2>
        <p className="mb-3 text-sm text-muted-foreground">
          Settings writes these to <code>~/.config/vocalinux/config.json</code>.
          The value <code>&quot;layout&quot;</code> is how Follow keyboard
          layout is stored:
        </p>
        <pre className="subpage-terminal overflow-x-auto p-4">
          <code>{`{
  "speech_recognition": {
    "language": "layout"
  },
  "shortcuts": {
    "language_shortcuts": [
      { "shortcut": "ctrl+alt+d", "language": "de" },
      { "shortcut": "f10", "language": "fr" }
    ]
  }
}`}</code>
        </pre>
        <p className="mt-3 text-sm text-muted-foreground">
          On whisper.cpp, Settings → Advanced (after Unlock Advanced Settings)
          also has Language Candidates: a comma-separated list such as{" "}
          <code>en,es</code> that restricts auto-detect to those languages.
          Leave it blank to consider all languages.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Engine caveats
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Engine</th>
                <th className="pb-3 pr-4 font-semibold">Language picker</th>
                <th className="pb-3 pr-4 font-semibold">Follow layout</th>
                <th className="pb-3 pr-4 font-semibold">Language shortcuts</th>
                <th className="pb-3 font-semibold">Notes</th>
              </tr>
            </thead>
            <tbody>
              {engineRows.map((row) => (
                <tr key={row.engine} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{row.engine}</td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.picker}
                  </td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.layout}
                  </td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.shortcuts}
                  </td>
                  <td className="py-3 text-muted-foreground">{row.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          VOSK lists only languages that have an official Alphacephei model, 21
          of the 33. Parakeet&apos;s v3-european model covers 25 European
          languages and ignores the picker; see{" "}
          <Link href="/parakeet/">Parakeet on Linux</Link>. For Whisper model
          sizes, see the{" "}
          <Link href="/whisper-model-guide/">Whisper model guide</Link>. The
          Remote API sends your audio to the endpoint you configured; details
          are on the <Link href="/remote-api/">Remote API page</Link>.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          The language catalog
        </h2>
        <p className="mb-4 text-muted-foreground">
          33 languages plus Auto-detect, shared by Settings, language shortcuts
          and the CLI. Slovenian was added in v0.18.4.
        </p>
        <div className="overflow-x-auto rounded-[12px] border border-border bg-background p-6">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Language</th>
                <th className="pb-3 pr-4 font-semibold">Code</th>
                <th className="pb-3 font-semibold">VOSK model</th>
              </tr>
            </thead>
            <tbody>
              {catalog.map((lang) => (
                <tr key={lang.code} className="border-b border-border">
                  <td className="py-2 pr-4 font-medium">{lang.name}</td>
                  <td className="py-2 pr-4">
                    <code>{lang.code}</code>
                  </td>
                  <td className="py-2 text-muted-foreground">
                    {lang.vosk ? (
                      <span className="inline-flex items-center gap-1.5">
                        <CheckCircle2
                          className="h-3.5 w-3.5 text-primary"
                          aria-hidden="true"
                        />
                        Yes
                      </span>
                    ) : (
                      "No (Whisper-family only)"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">FAQ</h2>
        <div className="space-y-4">
          {faqs.map((item) => (
            <div
              key={item.q}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 font-semibold">{item.q}</h3>
              <p className="text-sm text-muted-foreground">{item.a}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Dictate in your languages
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux, keep the default whisper.cpp engine with a
          multilingual model, and add a shortcut for each language you write in.
          Names and jargon in any language can go in the{" "}
          <Link href="/custom-dictionary/">custom dictionary</Link>.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/install/"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Install Vocalinux
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Link>
          <Link
            href="/languages/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Supported languages
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
