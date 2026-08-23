"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { SiteChrome } from "@/components/site-chrome";
import { TerminalBlock, TerminalPrompt } from "@/components/terminal-block";
import { GITHUB_REPO_URL } from "@/lib/seo";

const GITHUB_REPO_PATH = GITHUB_REPO_URL.replace("https://github.com/", "");
const GITHUB_RAW_BASE = `https://raw.githubusercontent.com/${GITHUB_REPO_PATH}`;

const installCommands = {
  interactiveInstallCommand: `curl -fsSL ${GITHUB_RAW_BASE}/main/install.sh -o /tmp/vl.sh && bash /tmp/vl.sh --interactive`,
  interactiveInstallDisplayCommand: `curl -fsSL \\
  ${GITHUB_RAW_BASE}/main/install.sh \\
  -o /tmp/vl.sh && \\
bash /tmp/vl.sh --interactive`,
  uninstallCommand: `curl -fsSL ${GITHUB_RAW_BASE}/main/uninstall.sh -o /tmp/vul.sh && bash /tmp/vul.sh`,
  uninstallDisplayCommand: `curl -fsSL \\
  ${GITHUB_RAW_BASE}/main/uninstall.sh \\
  -o /tmp/vul.sh && \\
bash /tmp/vul.sh`,
};

const homeJsonLd = [
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "@id": "https://vocalinux.com/#softwareapplication",
    name: "Vocalinux",
    applicationCategory: "UtilitiesApplication",
    operatingSystem: "Linux",
    isAccessibleForFree: true,
    license: `${GITHUB_REPO_URL}/blob/main/LICENSE`,
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "USD",
    },
    description:
      "Offline voice dictation and speech-to-text for Linux with whisper.cpp and VOSK.",
    softwareVersion: "0.15.0",
    author: {
      "@type": "Person",
      name: "Jatin K Malik",
      url: "https://github.com/jatinkrmalik",
    },
    url: "https://vocalinux.com/",
    downloadUrl: GITHUB_REPO_URL,
    screenshot: "https://vocalinux.com/og-image.png",
    featureList: [
      "Local speech recognition with whisper.cpp, Whisper, and VOSK",
      "Remote API speech recognition for compatible self-hosted transcription servers",
      "Silero neural voice activity detection with amplitude fallback",
      "Works with X11 and Wayland",
      "Toggle and push-to-talk shortcut modes",
      "Left/right modifier key distinction for shortcuts",
      "Optional voice commands with VOSK-aware defaults",
      "Searchable sidebar settings",
      "AppImage packages for x86_64 and aarch64",
      "Expanded speech-language catalog including Hungarian (per-engine availability)",
      "Auto-capitalize sentences after punctuation",
      "Trailing space after completed transcriptions for continuous dictation",
      "Auto-pause competing apps and idle model keep-alive unload",
      "Vulkan discrete GPU auto-select with manual device selection",
      "IBus via ibus-wayland on compositors that previously skipped IBus",
      "Adaptive audio and IBus-aware text injection",
      "Clipboard fallback for unsupported Wayland compositors",
      "Sound effects toggle for audio feedback",
      "whisper.cpp, Whisper, VOSK, and Remote API support",
      "Advanced whisper.cpp anti-hallucination settings",
      "Auto-recover speech recognition after system suspend/resume",
      "Safe engine switching without segfaults",
      "Keyboard layout preserved during IBus activation",
      "IBus runtime recovery and non-ASCII text injection fallback",
      "Push-to-talk mode with improved silence detection",
      "Linux desktop integration",
    ],
  },
  {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: [
      {
        "@type": "Question",
        name: "Does Vocalinux work offline?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Local engines process speech on your Linux machine. Remote API is optional and only talks to servers you configure.",
        },
      },
      {
        "@type": "Question",
        name: "Does Vocalinux collect usage telemetry?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "No. The installed app does not send usage telemetry, analytics events, or background usage pings. Even the project maintainer cannot see how many people install or actively use Vocalinux.",
        },
      },
      {
        "@type": "Question",
        name: "Which Linux distributions are supported?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Vocalinux supports Ubuntu, Fedora, Debian, Arch, Linux Mint, Pop!_OS, and other modern Linux distributions across X11 and Wayland.",
        },
      },
      {
        "@type": "Question",
        name: "How do I switch between speech engines?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Use the settings GUI or CLI flags for whisper.cpp, Whisper, VOSK, or Remote API. Open Settings from the tray and use the sidebar (search works). Remote API options live under Advanced.",
        },
      },
      {
        "@type": "Question",
        name: "What happens when I close my laptop lid?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Vocalinux v0.10.1+ automatically recovers speech recognition and keyboard shortcuts after system suspend/resume. No manual restart needed.",
        },
      },
      {
        "@type": "Question",
        name: "Does Vocalinux preserve my keyboard layout?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Yes. v0.10.1+ preserves your XKB keyboard layout when activating IBus, so you won't unexpectedly switch to US layout mid-dictation.",
        },
      },
    ],
  },
  {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: "Install Vocalinux on Linux",
    description: "Install offline voice dictation on Linux in a few minutes.",
    totalTime: "PT10M",
    step: [
      {
        "@type": "HowToStep",
        name: "Run the install command",
        text: "Copy the install command from vocalinux.com and run it in terminal.",
        url: "https://vocalinux.com/#install",
      },
      {
        "@type": "HowToStep",
        name: "Complete the guided setup",
        text: "Pick your speech engine and model size in the interactive installer.",
        url: "https://vocalinux.com/#install",
      },
      {
        "@type": "HowToStep",
        name: "Start dictating",
        text: "Launch vocalinux and hold Right Alt (Option) to begin dictation, or choose toggle mode in Settings.",
        url: "https://vocalinux.com/#install",
      },
    ],
  },
];

const engines = [
  {
    name: "whisper.cpp",
    badge: "Default",
    summary: "C++ Whisper with Vulkan. Fast install, multi-vendor GPU.",
    points: [
      "About 1-2 min default setup",
      "AMD / Intel / NVIDIA via Vulkan",
      "Tiny model ~74MB",
    ],
  },
  {
    name: "Whisper",
    summary: "Original OpenAI PyTorch path for NVIDIA CUDA workflows.",
    points: [
      "Same model family accuracy",
      "CUDA when you already live in PyTorch",
      "Larger install footprint",
    ],
  },
  {
    name: "VOSK",
    summary: "Small footprint for older machines and tight RAM budgets.",
    points: [
      "CPU-friendly streaming",
      "Models around ~40MB",
      "Great on modest hardware",
    ],
  },
  {
    name: "Remote API",
    summary: "Offload to a server you trust while keeping desktop injection local.",
    points: [
      "OpenAI-compatible endpoints",
      "whisper.cpp server support",
      "Local VAD still applies",
    ],
  },
];

const editorWords = [
  "the",
  "words",
  "go",
  "where",
  "you",
  "are",
  "already",
  "working",
];

function formatPanelClock(date: Date): string {
  const hours = date.getHours().toString().padStart(2, "0");
  const minutes = date.getMinutes().toString().padStart(2, "0");
  return `${hours}:${minutes}`;
}

const ribbonItems = [
  "Ubuntu",
  "Fedora",
  "Debian",
  "Arch",
  "X11",
  "Wayland",
  "on-device",
  "open source",
  "no account",
  "system tray",
  "whisper.cpp",
  "no telemetry",
];

export default function HomePage() {
  const [panelClock, setPanelClock] = useState("");
  const {
    interactiveInstallCommand,
    interactiveInstallDisplayCommand,
    uninstallCommand,
    uninstallDisplayCommand,
  } = installCommands;

  useEffect(() => {
    const tick = () => setPanelClock(formatPanelClock(new Date()));
    tick();
    const msToNextMinute = 60_000 - (Date.now() % 60_000);
    let intervalId = 0;
    const timeoutId = window.setTimeout(() => {
      tick();
      intervalId = window.setInterval(tick, 60_000);
    }, msToNextMinute);
    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    const track = document.querySelector(".ribbon-track");
    if (!(track instanceof HTMLElement)) return undefined;
    const onVisibility = () => {
      track.style.animationPlayState = document.hidden ? "paused" : "running";
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  return (
    <SiteChrome variant="home">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(homeJsonLd) }}
      />

      <section className="hero" id="top" aria-labelledby="hero-title">
        <div className="shell hero-inner">
          <div className="hero-copy min-w-0">
            <p className="section-tag">local Linux voice typing</p>
            <h1 id="hero-title" className="font-display">
              Dictate locally.
              <br />
              <em>In any app.</em>
            </h1>
            <p className="hero-lede">
              Hold Right Alt. Text lands in the focused window. Local engines
              by default.
            </p>
            <div className="hero-cta">
              <div className="hero-actions">
                <a className="btn btn-primary" href="#install">
                  Install Vocalinux{" "}
                  <span className="btn-arrow btn-arrow-down" aria-hidden="true">
                    ↓
                  </span>
                </a>
                <a
                  className="btn btn-secondary"
                  href={GITHUB_REPO_URL}
                  rel="noopener noreferrer"
                >
                  View the source{" "}
                  <span className="btn-arrow" aria-hidden="true">
                    ↗
                  </span>
                </a>
              </div>
              <p className="hero-cta-note">No account. One install command.</p>
            </div>
            <div className="hero-proof">
              <span>X11 and Wayland</span>
              <span>No telemetry</span>
              <span>AGPL-3.0</span>
            </div>
          </div>

          <div
            className="workbench min-w-0"
            role="img"
            aria-label="Vocalinux listening from the system tray and inserting text into a Linux editor"
          >
            <div className="panel-bar">
              <span>Vocalinux</span>
              <span className="panel-status">
                <i className="rec-dot" aria-hidden="true"></i>
                listening
              </span>
              <span className="panel-clock">{panelClock}</span>
            </div>
            <div className="linux-window">
              <div className="linux-titlebar">
                <span className="window-title">notes.txt</span>
                <span className="linux-controls" aria-hidden="true">
                  <i></i>
                  <i></i>
                  <i className="close"></i>
                </span>
              </div>
              <div className="window-body">
                <div className="workbench-header">
                  <div>
                    <strong>Ready to dictate</strong>
                    <span className="workbench-hint">
                      Hold Right Alt to record
                    </span>
                  </div>
                  <span className="status-badge">
                    <i aria-hidden="true"></i> local
                  </span>
                </div>
                <div className="waveform" aria-hidden="true">
                  {Array.from({ length: 28 }, (_, index) => (
                    <i key={index}></i>
                  ))}
                </div>
                <div className="editor-line">
                  <span className="editor-text">
                    {editorWords.map((word, index) => (
                      <React.Fragment key={word}>
                        {index > 0 ? " " : null}
                        <span>{word}</span>
                      </React.Fragment>
                    ))}
                  </span>
                  <i className="caret" aria-hidden="true"></i>
                </div>
                <div className="workbench-meta">
                  <span className="chip">whisper.cpp default</span>
                  <span className="chip">Whisper</span>
                  <span className="chip">VOSK</span>
                  <span className="chip">Remote API</span>
                </div>
              </div>
            </div>
            <div className="workbench-terminal">
              <div className="terminal-chrome">
                <span className="window-title">~/bin</span>
                <span className="linux-controls" aria-hidden="true">
                  <i></i>
                  <i></i>
                  <i className="close"></i>
                </span>
              </div>
              <pre>
                <TerminalPrompt />
                vocalinux
                {"\n"}
                <span className="terminal-comment">
                  # audio stays on this machine
                </span>
              </pre>
            </div>
          </div>
        </div>
      </section>

      <section className="ribbon" aria-label="Supported Linux environments">
        <div className="ribbon-track">
          {[0, 1].map((copy) => (
            <div
              className="ribbon-group"
              key={copy}
              aria-hidden={copy === 1 ? true : undefined}
            >
              {Array.from({ length: 4 }, (_, repeat) =>
                ribbonItems.map((item) => (
                  <React.Fragment key={`${copy}-${repeat}-${item}`}>
                    <span>{item}</span>
                    <b aria-hidden="true">·</b>
                  </React.Fragment>
                )),
              )}
            </div>
          ))}
        </div>
      </section>

      <section
        className="band band-bright"
        id="how-it-works"
        aria-labelledby="how-title"
      >
        <div className="shell">
          <div className="section-head">
            <h2 className="section-title" id="how-title">
              A small loop that stays out of the way.
            </h2>
            <p className="section-lede">
              Vocalinux lives in the system tray, so dictation starts where your
              work already is.
            </p>
          </div>
          <div className="story-list">
            <article className="story-row">
              <div className="story-index" aria-hidden="true">
                01
              </div>
              <div className="story-copy">
                <p className="story-label">hold / shortcut</p>
                <h3>Speak where you already type.</h3>
                <p>
                  Hold Right Alt, or switch to toggle mode. The tray tells you
                  when Vocalinux is listening, then text lands in the focused
                  field.
                </p>
              </div>
              <div
                className="story-visual"
                role="img"
                aria-label="A shortcut hint and a text field receiving a transcript"
              >
                <div className="chip">Right Alt</div>
                <div className="editor-line" style={{ marginTop: "0.85rem" }}>
                  the words go where you are already working
                  <i className="caret" aria-hidden="true"></i>
                </div>
              </div>
            </article>

            <article className="story-row story-row-reverse">
              <div className="story-index" aria-hidden="true">
                02
              </div>
              <div className="story-copy">
                <p className="story-label">model / path</p>
                <h3>Choose where the model runs.</h3>
                <p>
                  On-device mode is the default: download a speech-to-text
                  model and process here. If you want shared compute, point
                  Remote API at a server you run.
                </p>
              </div>
              <div
                className="story-visual"
                role="img"
                aria-label="On-device and optional remote API paths"
              >
                <div className="path-note">
                  <span className="path-number">A</span>
                  <div>
                    <strong>this machine</strong>
                    <p>model and audio stay here</p>
                  </div>
                  <span aria-hidden="true">✓</span>
                </div>
                <div className="path-divider">
                  <span>or</span>
                </div>
                <div className="path-note">
                  <span className="path-number">B</span>
                  <div>
                    <strong>your Remote API</strong>
                    <p>a server URL you configure</p>
                  </div>
                  <span aria-hidden="true">↗</span>
                </div>
              </div>
            </article>

            <article className="story-row">
              <div className="story-index" aria-hidden="true">
                03
              </div>
              <div className="story-copy">
                <p className="story-label">insert / desktop</p>
                <h3>Keep working in any app.</h3>
                <p>
                  Terminals, browsers, IDEs, and office apps on X11 or Wayland.
                  Injection uses IBus when it is available, with clipboard
                  fallback on unbridged compositors.
                </p>
              </div>
              <div
                className="story-visual"
                role="img"
                aria-label="Apps that receive inserted text"
              >
                <div className="workbench-meta">
                  <span className="chip">terminal</span>
                  <span className="chip">browser</span>
                  <span className="chip">IDE</span>
                  <span className="chip">X11</span>
                  <span className="chip">Wayland</span>
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section
        className="band band-deep"
        id="engines"
        aria-labelledby="engines-title"
      >
        <div className="shell">
          <div className="section-head">
            <h2 className="section-title" id="engines-title">
              The engine is a setting, not a mystery.
            </h2>
            <p className="section-lede">
              Local engines process audio on this machine. Remote API is
              optional and only talks to a server you configure.
            </p>
          </div>
          <div className="engine-list">
            {engines.map((engine) => (
              <div className="engine-row min-w-0" key={engine.name}>
                <div>
                  <h3>{engine.name}</h3>
                  {engine.badge ? (
                    <span className="chip" style={{ marginTop: "0.45rem" }}>
                      {engine.badge}
                    </span>
                  ) : null}
                </div>
                <div className="min-w-0">
                  <p>{engine.summary}</p>
                  <ul className="engine-points">
                    {engine.points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                </div>
              </div>
            ))}
          </div>
          <p className="section-link">
            <Link href="/compare/">
              Full engine comparison{" "}
              <span className="btn-arrow" aria-hidden="true">
                →
              </span>
            </Link>
          </p>
        </div>
      </section>

      <section className="band" id="proof" aria-labelledby="proof-title">
        <div className="shell">
          <div className="section-head">
            <h2 className="section-title" id="proof-title">
              A Linux app you can actually see working.
            </h2>
            <p className="section-lede">
              Tray, settings, and dictation into a real editor. These are
              product states, not a dashboard mock.
            </p>
          </div>
          <div className="proof-grid">
            <figure className="shot shot-frame">
              <Image
                src="/screenshots/00-transcription.png"
                alt="Vocalinux dictating into a text editor with the tray menu open"
                width={2518}
                height={2057}
                className="h-auto w-full"
              />
              <figcaption>
                <strong>Dictation in the focused app</strong>
                Hold the shortcut and text lands where you were already typing.
              </figcaption>
            </figure>
            <figure className="shot shot-frame">
              <Image
                src="/screenshots/settings-speech-engine.png"
                alt="Vocalinux settings dialog showing speech engine options"
                width={2128}
                height={1698}
                className="h-auto w-full"
              />
              <figcaption>
                <strong>Engine and model controls</strong>
                Pick whisper.cpp, Whisper, VOSK, or a Remote API you trust.
              </figcaption>
            </figure>
            <figure className="shot shot-frame">
              <Image
                src="/screenshots/02-system-tray.png"
                alt="Vocalinux system tray icon and menu"
                width={315}
                height={466}
                className="mx-auto h-auto max-h-[18rem] w-auto object-contain"
              />
              <figcaption>
                <strong>Tray while you work</strong>
                Start, stop, settings, and logs without leaving the desktop.
              </figcaption>
            </figure>
          </div>
          <p className="section-link">
            <Link href="/screenshots/">
              See the screenshot gallery{" "}
              <span className="btn-arrow" aria-hidden="true">
                →
              </span>
            </Link>
          </p>
        </div>
      </section>

      <section
        className="band band-deep"
        id="privacy"
        aria-labelledby="privacy-title"
      >
        <div className="shell">
          <div className="section-head">
            <h2 className="section-title" id="privacy-title">
              Your voice has a path. We show you which one.
            </h2>
            <p className="section-lede">
              Vocalinux does not need a Voca cloud to transcribe. The important
              boundary is the engine you selected.
            </p>
          </div>
          <ol className="route">
            <li>
              <div className="route-node">
                <span className="route-name">Microphone</span>
                <span className="route-sub">You hold the hotkey</span>
              </div>
            </li>
            <li>
              <div className="route-node">
                <span className="route-name">In-memory audio</span>
                <span className="route-sub">Held for the recording</span>
              </div>
            </li>
            <li>
              <div className="route-node">
                <span className="route-name">Local speech engine</span>
                <span className="route-sub">Runs on this Linux machine</span>
              </div>
            </li>
            <li>
              <div className="route-node">
                <span className="route-name">Transcript at cursor</span>
                <span className="route-sub">Where you were typing</span>
              </div>
            </li>
          </ol>
          <p className="route-negative">
            <span>
              <strong>Remote API is a separate stop.</strong> If you configure a
              server URL, audio travels to that host and the transcript comes
              back. Use a trusted LAN, a private encrypted network, or HTTPS.
            </span>
          </p>
          <div className="boundaries">
            <article className="boundary">
              <h3>What stays local</h3>
              <p>
                Default engines process audio on this machine. The installed app
                does not send usage telemetry.
              </p>
            </article>
            <article className="boundary">
              <h3>What uses a network</h3>
              <p>
                Model and app downloads, plus any Remote API host you add.
                Nothing is sent to a Voca speech cloud.
              </p>
            </article>
            <article className="boundary">
              <h3>What you can inspect</h3>
              <p>
                The application is open source under AGPL-3.0. Settings, engines,
                and the injection path are in the repository.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section
        className="band"
        id="install"
        aria-labelledby="install-title"
      >
        <div className="shell min-w-0">
          <div className="section-head">
            <h2 className="section-title" id="install-title">
              Install in one command.
            </h2>
            <p className="section-lede">
              The interactive installer detects hardware, lets you pick an
              engine, and wires the desktop app. Ubuntu, Fedora, Debian, Arch,
              and openSUSE.
            </p>
          </div>
          <TerminalBlock
            command={interactiveInstallCommand}
            displayCommand={interactiveInstallDisplayCommand}
            label="install.sh --interactive"
          />
          <p className="section-lede">Then launch <code>vocalinux</code>.</p>
          <div className="install-alts">
            <a
              className="install-alt"
              href={`${GITHUB_REPO_URL}/releases`}
              rel="noopener noreferrer"
            >
              <p className="install-alt-kicker">No installer</p>
              <h3>AppImage</h3>
              <p>
                x86_64 or aarch64 from GitHub Releases. No root. Host
                text-injection tools are still required.
              </p>
            </a>
            <a
              className="install-alt"
              href={`${GITHUB_REPO_URL}/blob/main/docs/INSTALL.md#from-source`}
              rel="noopener noreferrer"
            >
              <p className="install-alt-kicker">From source</p>
              <h3>Build it yourself</h3>
              <p>
                Clone the repo and run <code>./install.sh</code>. The install
                guide has the full source path.
              </p>
            </a>
          </div>
          <p className="section-link" style={{ marginTop: "1.6rem" }}>
            <Link href="/install/ubuntu/">Ubuntu guide</Link>
            {" · "}
            <Link href="/install/fedora/">Fedora guide</Link>
            {" · "}
            <Link href="/install/arch/">Arch guide</Link>
            {" · "}
            <Link href="/install/">All distro notes</Link>
          </p>
          <div className="section-head" style={{ marginTop: "3.5rem" }}>
            <h3 className="section-title" style={{ fontSize: "clamp(1.6rem, 3vw, 2.2rem)" }}>
              Uninstall
            </h3>
          </div>
          <TerminalBlock
            command={uninstallCommand}
            displayCommand={uninstallDisplayCommand}
            label="uninstall.sh"
          />
        </div>
      </section>

      <section className="band band-deep" id="faq" aria-labelledby="faq-title">
        <div className="shell">
          <div className="section-head">
            <h2 className="section-title" id="faq-title">
              Questions, answered.
            </h2>
          </div>
          <div className="faq-list">
            {(
              [
                {
                  question: "Does Vocalinux work offline?",
                  answer: (
                    <>
                      Local engines (whisper.cpp, Whisper, and VOSK) process
                      speech on your machine. Remote API is optional and only
                      talks to servers you configure.{" "}
                      <Link href="/offline/">Offline details</Link>.
                    </>
                  ),
                  open: true,
                },
                {
                  question: "Does Vocalinux collect usage telemetry?",
                  answer:
                    "No. The installed app does not send usage telemetry, analytics events, or background usage pings.",
                },
                {
                  question: "Which Linux distributions are supported?",
                  answer: (
                    <>
                      Ubuntu 22.04+, Debian 11+, Fedora 39+, Arch, openSUSE
                      Tumbleweed, and most modern desktops on X11 or Wayland.{" "}
                      <Link href="/install/">Install guides</Link>.
                    </>
                  ),
                },
                {
                  question: "How do I switch between speech engines?",
                  answer: (
                    <>
                      Settings dialog or CLI:{" "}
                      <code>--engine whisper_cpp</code>, <code>whisper</code>,{" "}
                      <code>vosk</code>, or <code>remote_api</code>.{" "}
                      <Link href="/compare/">Compare engines</Link>.
                    </>
                  ),
                },
                {
                  question: "Can Vocalinux use a remote transcription server?",
                  answer: (
                    <>
                      Yes. OpenAI-compatible Whisper servers and the whisper.cpp
                      server endpoint under Settings → Advanced → Remote Server.{" "}
                      <Link href="/remote-api/">Remote API guide</Link>.
                    </>
                  ),
                },
                {
                  question: "What happens when I close my laptop lid?",
                  answer: (
                    <>
                      v0.10.1+ recovers speech recognition and shortcuts after
                      suspend/resume.{" "}
                      <Link href="/desktop-reliability/">
                        Reliability notes
                      </Link>
                      .
                    </>
                  ),
                },
                {
                  question: "Does Vocalinux preserve my keyboard layout?",
                  answer:
                    "Yes. v0.10.1+ keeps your XKB layout when activating IBus.",
                },
                {
                  question: "Is Vocalinux free?",
                  answer: (
                    <>
                      Yes. Free and open source under AGPL-3.0, no premium
                      tiers. <Link href="/open-source/">About the project</Link>
                      .
                    </>
                  ),
                },
              ] as {
                question: string;
                answer: React.ReactNode;
                open?: boolean;
              }[]
            ).map((item) => (
              <details key={item.question} open={item.open}>
                <summary>
                  {item.question}
                  <span className="faq-mark" aria-hidden="true">
                    +
                  </span>
                </summary>
                <div>{item.answer}</div>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="band" id="ecosystem" aria-labelledby="family-title">
        <div className="shell">
          <div className="section-head">
            <h2 className="section-title" id="family-title">
              Same promise, other machines.
            </h2>
            <p className="section-lede">
              Vocalinux is part of{" "}
              <a href="https://vocahq.com" rel="noopener noreferrer">
                VocaHQ
              </a>
              . This site is about the Linux app.
            </p>
          </div>
          <div className="family-grid">
            <div className="family-card is-here">
              <div className="family-card-top">
                <span className="family-platform">
                  <img
                    src="/brand/platforms/linux.svg"
                    alt=""
                    width={22}
                    height={22}
                  />
                  Linux
                </span>
                <span className="chip">You are here</span>
              </div>
              <h3>Vocalinux</h3>
              <p>
                System tray app with whisper.cpp, Vulkan, and local engines on
                Linux.
              </p>
            </div>
            <a className="family-card" href="https://vocamac.com">
              <div className="family-card-top">
                <span className="family-platform">
                  <img
                    src="/brand/platforms/apple.svg"
                    alt=""
                    width={22}
                    height={22}
                  />
                  macOS
                </span>
                <span className="chip">Beta</span>
              </div>
              <h3>VocaMac</h3>
              <p>
                Native macOS menu bar app. Offline voice-to-text with WhisperKit
                and CoreML.
              </p>
            </a>
            <a className="family-card" href="https://vocawin.com">
              <div className="family-card-top">
                <span className="family-platform">
                  <img
                    src="/brand/platforms/windows.svg"
                    alt=""
                    width={22}
                    height={22}
                  />
                  Windows
                </span>
                <span className="chip">Developer alpha</span>
              </div>
              <h3>VocaWin</h3>
              <p>
                Unsigned Windows speech-to-text. SmartScreen may warn about an
                unknown publisher.
              </p>
            </a>
            <a className="family-card" href="https://vocaphone.vocahq.com">
              <div className="family-card-top">
                <span className="family-platform">
                  <span className="family-platform-pair">
                    <img
                      src="/brand/platforms/apple.svg"
                      alt=""
                      width={20}
                      height={20}
                    />
                    <img
                      src="/brand/platforms/android.svg"
                      alt=""
                      width={20}
                      height={20}
                    />
                  </span>
                  iPhone + Android
                </span>
                <span className="chip">Phone beta</span>
              </div>
              <h3>VocaPhone</h3>
              <p>
                Android beta and iOS TestFlight. On-device first, gateway
                optional.
              </p>
            </a>
            <a
              className="family-card"
              href="https://vocagateway.vocahq.com/"
            >
              <div className="family-card-top">
                <span className="family-platform">
                  <img
                    src="/brand/platforms/server.svg"
                    alt=""
                    width={22}
                    height={22}
                  />
                  Infrastructure
                </span>
                <span className="chip">Early</span>
              </div>
              <h3>VocaGateway</h3>
              <p>
                Optional self-hosted speech-to-text on hardware you run. Not
                on-device.
              </p>
            </a>
          </div>
        </div>
      </section>

      <section className="band band-bright final-cta">
        <div className="shell">
          <h2 className="section-title">Install and try a real dictation session.</h2>
          <p className="section-lede">
            Free and open source under AGPL-3.0. Local engines by default.
          </p>
          <div className="hero-cta">
            <div className="hero-actions">
              <a className="btn btn-primary" href="#install">
                Install Vocalinux
              </a>
              <a
                className="btn btn-secondary"
                href={GITHUB_REPO_URL}
                rel="noopener noreferrer"
              >
                View the source
              </a>
            </div>
            <p className="hero-cta-note">
              Then hold Right Alt and speak into the app already in front of you.
            </p>
          </div>
        </div>
      </section>
    </SiteChrome>
  );
}
