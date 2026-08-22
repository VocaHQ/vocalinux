import Link from "next/link";
import { type Metadata } from "next";
import { Camera, ChevronRight, Download } from "lucide-react";
import {
  ScreenshotGallery,
  type Screenshot,
} from "@/components/screenshot-gallery";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

/** Pixel size of the captured settings/log dialog screenshots. */
const SETTINGS_SIZE = { width: 2128, height: 1698 } as const;

const productShots: Screenshot[] = [
  {
    src: "/screenshots/00-transcription.png",
    srcDark: "/screenshots/dark/00-transcription.png",
    alt: "Vocalinux dictating into a text editor with the tray menu open",
    title: "Dictation in action",
    description:
      "Voice typing into a focused app while the tray menu shows listening state.",
    width: 2518,
    height: 2057,
  },
  {
    src: "/screenshots/02-system-tray.png",
    srcDark: "/screenshots/dark/02-system-tray.png",
    alt: "Vocalinux system tray menu with voice typing controls",
    title: "System tray",
    description: "Tray menu for start/stop, settings, logs, and about.",
    width: 315,
    height: 466,
  },
  {
    src: "/screenshots/03-log-viewer.png",
    srcDark: "/screenshots/dark/03-log-viewer.png",
    alt: "Vocalinux log viewer dialog",
    title: "Log viewer",
    description: "Inspect runtime logs when diagnosing dictation issues.",
    ...SETTINGS_SIZE,
  },
];

const settingsShots: Screenshot[] = [
  {
    src: "/screenshots/settings-speech-engine.png",
    srcDark: "/screenshots/dark/settings-speech-engine.png",
    alt: "Vocalinux Speech Model settings with sidebar navigation",
    title: "Speech Model",
    description:
      "Choose whisper.cpp, Whisper, VOSK, or Remote API and pick a model.",
    ...SETTINGS_SIZE,
  },
  {
    src: "/screenshots/settings-recognition.png",
    srcDark: "/screenshots/dark/settings-recognition.png",
    alt: "Vocalinux Dictation settings page",
    title: "Dictation",
    description: "Shortcuts, listening controls, and dictation output options.",
    ...SETTINGS_SIZE,
  },
  {
    src: "/screenshots/settings-audio.png",
    srcDark: "/screenshots/dark/settings-audio.png",
    alt: "Vocalinux Audio settings page",
    title: "Audio",
    description: "Input device, feedback sounds, and capture options.",
    ...SETTINGS_SIZE,
  },
  {
    src: "/screenshots/settings-performance.png",
    srcDark: "/screenshots/dark/settings-performance.png",
    alt: "Vocalinux Performance settings page",
    title: "Performance",
    description: "Auto-pause, model keep-alive, and GPU device selection.",
    ...SETTINGS_SIZE,
  },
  {
    src: "/screenshots/settings-general.png",
    srcDark: "/screenshots/dark/settings-general.png",
    alt: "Vocalinux Application settings page",
    title: "Application",
    description: "Autostart, start minimized, and everyday defaults.",
    ...SETTINGS_SIZE,
  },
  {
    src: "/screenshots/settings-advanced.png",
    srcDark: "/screenshots/dark/settings-advanced.png",
    alt: "Vocalinux Advanced settings with whisper.cpp decoding controls",
    title: "Advanced",
    description: "Power-user decoding controls and Remote Server options.",
    ...SETTINGS_SIZE,
  },
  {
    src: "/screenshots/05-about-view.png",
    srcDark: "/screenshots/dark/05-about-view.png",
    alt: "Vocalinux About settings page with update checker",
    title: "About",
    description:
      "Version info plus Stable/Nightly update checks from GitHub Releases.",
    ...SETTINGS_SIZE,
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Vocalinux Screenshots | Linux Voice Dictation UI",
  description:
    "See Vocalinux in action: system tray, log viewer, and settings pages for speech model, dictation, audio, performance, application, advanced options, and about/updates. Flip between light and dark app shots.",
  path: "/screenshots",
  keywords: [
    "Vocalinux screenshots",
    "Linux voice dictation UI",
    "offline speech recognition settings",
    "whisper.cpp Linux screenshots",
    "voice typing system tray Linux",
  ],
});

export default function ScreenshotsPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "ImageGallery",
    name: "Vocalinux Screenshots",
    description:
      "Product and settings screenshots of Vocalinux, offline voice dictation for Linux.",
    dateModified: "2026-08-03", // refreshed after About moved into Settings sidebar
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
    mainEntityOfPage: absoluteUrl("/screenshots"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="border-primary/30 bg-primary/10 mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium text-primary">
          <Camera className="h-4 w-4" />
          v0.15 UI
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Vocalinux Screenshots
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          A look at offline voice dictation on Linux: tray controls, debugging
          tools, and the searchable sidebar settings UI from v0.15. Flip light
          and dark app shots. Click any image to expand it.
        </p>
      </section>

      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />

      <section className="border-primary/20 bg-primary/5 rounded-[12px] border p-8">
        <h2 className="mb-3 font-display text-2xl font-semibold">Try it yourself</h2>
        <p className="mb-6 max-w-2xl text-muted-foreground">
          Install Vocalinux and open Settings from the system tray to explore
          the same screens on your desktop.
        </p>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Link
            href="/install/"
            className="inline-flex items-center justify-center gap-2 rounded-[12px] bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground"
          >
            <Download className="h-4 w-4" />
            Install guide
            <ChevronRight className="h-4 w-4" />
          </Link>
          <Link
            href="/advanced-settings/"
            className="inline-flex items-center justify-center gap-2 rounded-[12px] border border-border bg-background px-5 py-3 text-sm font-semibold transition-colors hover:bg-muted"
          >
            Advanced settings guide
            <ChevronRight className="h-4 w-4" />
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
