import Link from "next/link";
import { type Metadata } from "next";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  Lightbulb,
  Terminal,
  Wrench,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const troubleshootingItems = [
  {
    title: "Vocalinux won't start",
    symptoms: [
      "Command not found",
      "Module import errors",
      "Application crashes on launch",
    ],
    solutions: [
      "Ensure you ran the installer from the homepage or install guide",
      "Check if the virtual environment is activated: source ~/.local/share/vocalinux/venv/bin/activate",
      "Verify Python version (3.9+ required): python3 --version",
      "Try reinstalling: ./uninstall.sh && ./install.sh",
    ],
  },
  {
    title: "No audio detected / microphone not working",
    symptoms: [
      "Dictation shows no text",
      "Audio level indicator stays at zero",
    ],
    solutions: [
      "Check microphone permissions in your system settings",
      "Verify microphone is detected: arecord -l (Linux)",
      "Test microphone recording: arecord -d 3 test.wav && aplay test.wav",
      "Ensure no other application is using the microphone",
      "Check PulseAudio/PipeWire settings: pavucontrol",
    ],
  },
  {
    title: "Text not appearing in applications",
    symptoms: [
      "Dictation works but text doesn't appear",
      "Text injection fails",
    ],
    solutions: [
      "For Wayland: Ensure IBus is running and Vocalinux IBus is configured",
      "For X11: Verify xdotool is installed: sudo apt install xdotool",
      "Check if the target application has focus",
      "Try a different application (terminal, text editor) to isolate the issue",
      "Restart Vocalinux after changing display servers",
    ],
  },
  {
    title: "High CPU/GPU usage",
    symptoms: [
      "System slowdown during dictation",
      "Fan noise",
      "Laggy response",
    ],
    solutions: [
      "Use a smaller model (tiny or base instead of medium/large)",
      "Enable GPU acceleration if available (Vulkan for AMD/Intel, CUDA for NVIDIA)",
      "Switch to VOSK engine for lower resource usage",
      "Reduce audio sample rate in settings",
    ],
  },
  {
    title: "Poor transcription accuracy",
    symptoms: ["Many transcription errors", "Wrong words", "Garbled text"],
    solutions: [
      "Use a larger model (small → medium → large) for better accuracy",
      "Ensure microphone is positioned correctly and not too far",
      "Reduce background noise",
      "Speak clearly and at a moderate pace",
      "Try a different speech engine (whisper.cpp vs VOSK)",
      "Set the correct language in settings",
    ],
  },
  {
    title: "Remote API transcription fails",
    symptoms: [
      "Connection test fails",
      "HTTP 401/403 errors",
      "HTTP 404 on transcription",
    ],
    solutions: [
      "Confirm the server URL is reachable from the Vocalinux machine",
      "Check whether the server expects /inference or /v1/audio/transcriptions",
      "Set the API key if your server requires bearer token authentication",
      "Use HTTPS and a firewall when the server is outside a trusted LAN",
    ],
  },
  {
    title: "Silero VAD is not active",
    symptoms: [
      "Recognition tab shows amplitude VAD",
      "Silence-only buffers still appear",
    ],
    solutions: [
      'Install neural VAD support: pip install "vocalinux[vad]"',
      "Restart Vocalinux after installing ONNX Runtime support",
      "Use the VAD sensitivity setting in Recognition to tune quiet speech detection",
      "If Silero cannot load, Vocalinux falls back safely to amplitude-based VAD",
    ],
  },
  {
    title: "Installation fails",
    symptoms: ["Dependency errors", "Package not found", "Permission denied"],
    solutions: [
      "Ensure you have internet connectivity for downloading dependencies",
      "Run with sufficient permissions (don't use sudo unless specifically needed)",
      "Check your distribution is supported (Ubuntu 22.04+, Fedora 39+, Arch)",
      "Install system dependencies manually: sudo apt install python3-pip python3-gi python3-venv",
      "Check disk space: df -h",
    ],
  },
  {
    title: "Keyboard shortcut not working",
    symptoms: [
      "Shortcut mode doesn't start dictation",
      "Custom shortcuts ignored",
    ],
    solutions: [
      "Check if another application is capturing the shortcut",
      "Verify Vocalinux is running (check system tray)",
      "Try changing the shortcut in Settings",
      "On Wayland, ensure keyboard shortcuts are not blocked by compositor settings",
    ],
  },
  {
    title: "Vocalinux stops working after system suspend/resume",
    symptoms: [
      "Dictation doesn't start after laptop wakes",
      "Keyboard shortcuts stop working",
      "App appears running but not responding",
    ],
    solutions: [
      "v0.10.1+ automatically recovers after suspend - ensure you're on latest version",
      "Check system tray icon status after resume",
      "If issues persist, restart Vocalinux from tray menu",
    ],
  },
  {
    title: "Tray icon not appearing",
    symptoms: ["No system tray icon", "Cannot access settings"],
    solutions: [
      "v0.10.1+ bundles resources to prevent missing tray icons - ensure you're on latest version",
      "Ensure your desktop environment supports system trays (GNOME requires an AppIndicator extension)",
      "Install the GNOME AppIndicator extension (pick your distro): Debian/Ubuntu: sudo apt install gnome-shell-extension-appindicator — Fedora: sudo dnf install gnome-shell-extension-appindicator — Arch: sudo pacman -S gnome-shell-extension-appindicator",
      "Then enable the extension (Extensions app, or: gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com) and log out/in if needed",
      "Debian/Ubuntu: sudo apt install libayatana-appindicator3-1 — Fedora: sudo dnf install libayatana-appindicator-gtk3 — Arch: sudo pacman -S libayatana-appindicator (legacy libappindicator-gtk3 can leave the icon missing on KDE)",
      "Try launching from terminal to see any errors: vocalinux --debug",
    ],
  },
  {
    title: "Settings dialog missing close button",
    symptoms: ["Cannot close settings window", "Close button not visible"],
    solutions: [
      "v0.10.1+ includes dedicated close button - update to latest version",
      "Settings dialog now forces window decorations",
    ],
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Troubleshooting Guide - Vocalinux Voice Dictation",
  description:
    "Fix common Vocalinux issues: microphone problems, text injection, installation errors, and performance. Step-by-step solutions for Linux voice dictation.",
  path: "/troubleshooting",
  keywords: [
    "vocalinux troubleshooting",
    "linux voice dictation problems",
    "speech to text not working",
    "microphone issues linux",
  ],
});

export default function TroubleshootingPage() {
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Vocalinux Troubleshooting Guide",
    description:
      "Complete troubleshooting guide for Vocalinux Linux voice dictation software.",
    dateModified: "2026-06-11",
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
    mainEntityOfPage: absoluteUrl("/troubleshooting"),
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }}
      />

      <section>
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-muted px-4 py-1.5 text-sm font-medium text-muted-foreground">
          <Wrench className="h-4 w-4" />
          Support Guide
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Troubleshooting Guide
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Having issues with Vocalinux? Find solutions to common problems below.
          Can't find your issue? Open a GitHub issue for help.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 text-xl font-semibold">
          <Terminal className="h-5 w-5 text-primary" />
          Quick Debug Command
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Run Vocalinux with debug output to see detailed logs:
        </p>
        <div className="rounded-lg bg-[color:var(--terminal)] p-4">
          <code className="text-sm text-[color:var(--terminal-fg)]">vocalinux --debug</code>
        </div>
      </section>

      <section className="space-y-6">
        {troubleshootingItems.map((item) => (
          <article
            key={item.title}
            className="rounded-[12px] border border-border bg-background p-6"
          >
            <h2 className="mb-4 text-xl font-semibold">{item.title}</h2>

            <div className="mb-4 rounded-lg bg-muted p-4 dark:bg-muted">
              <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <AlertTriangle className="h-4 w-4" />
                Symptoms
              </p>
              <ul className="ml-6 list-disc text-sm text-muted-foreground">
                {item.symptoms.map((symptom) => (
                  <li key={symptom} className="break-words">
                    {symptom}
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-lg bg-primary/10 p-4 dark:bg-primary/10">
              <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-primary dark:text-[color:var(--terminal-fg)]">
                <CheckCircle2 className="h-4 w-4" />
                Solutions
              </p>
              <ul className="ml-6 list-disc text-sm text-primary">
                {item.solutions.map((solution) => (
                  <li key={solution} className="break-words">
                    {solution}
                  </li>
                ))}
              </ul>
            </div>
          </article>
        ))}
      </section>

      <section className="mt-12 rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <Lightbulb className="h-5 w-5 text-primary" />
          Still having issues?
        </h2>
        <ul className="space-y-3 text-muted-foreground">
          <li className="flex items-start gap-2">
            <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              Check the{" "}
              <Link
                href="/faq/"
                className="font-semibold text-primary hover:underline"
              >
                FAQ page
              </Link>{" "}
              for common questions
            </span>
          </li>
          <li className="flex items-start gap-2">
            <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              Review{" "}
              <Link
                href="/remote-api/"
                className="font-semibold text-primary hover:underline"
              >
                Remote API setup
              </Link>{" "}
              or{" "}
              <Link
                href="/voice-activity-detection/"
                className="font-semibold text-primary hover:underline"
              >
                Silero VAD behavior
              </Link>{" "}
              for newer recognition features
            </span>
          </li>
          <li className="flex items-start gap-2">
            <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <a
                href="https://github.com/VocaHQ/vocalinux/issues"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"
              >
                Search existing issues on GitHub
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </span>
          </li>
          <li className="flex items-start gap-2">
            <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
            <span>
              <a
                href="https://github.com/VocaHQ/vocalinux/issues/new"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"
              >
                Open a new issue (include debug logs)
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </span>
          </li>
        </ul>
      </section>
    </SeoSubpageShell>
  );
}
