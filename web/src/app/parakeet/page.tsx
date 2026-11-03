import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Cpu,
  Download,
  Globe,
  Lock,
  XCircle,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const installCommands = [
  "curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh",
  "bash /tmp/vl.sh --auto --engine=parakeet",
];

const setupSteps = [
  {
    title: "Install the Parakeet engine",
    text: "Parakeet is an optional extra. Download the installer and run it with --engine=parakeet. The interactive engine menu does not list Parakeet, so pass the flag. The installer adds sherpa-onnx and points your config at the Parakeet engine.",
  },
  {
    title: "Open Settings → Speech Model",
    text: "Open Settings from the tray icon and go to Speech Model. Expand Advanced to see the Engine and Model size pickers.",
  },
  {
    title: "Pick Parakeet and a model",
    text: "Set Engine to Parakeet, then choose v3-european, v2-english or orukeet-v0.1.0 under Model size. Picking only selects the model; nothing downloads yet.",
  },
  {
    title: "Confirm the download",
    text: "If the model is not on disk, the info card shows its size and a Download button. The transfer starts only after you confirm it. Each file is checked against a pinned SHA-256 before Parakeet loads it.",
  },
  {
    title: "Dictate",
    text: "Hold your dictation shortcut (Right Alt by default on new installs), speak, and release. Text is typed into the focused app.",
  },
];

const models = [
  {
    id: "v3-european",
    name: "Parakeet TDT 0.6B v3 (int8)",
    languages: "25 European languages",
    size: "about 639 MB",
    notes: "Default and recommended Parakeet model.",
  },
  {
    id: "v2-english",
    name: "Parakeet TDT 0.6B v2 (int8)",
    languages: "English only",
    size: "about 630 MB",
    notes: "Pick this if you only dictate in English.",
  },
  {
    id: "orukeet-v0.1.0",
    name: "Orukeet v0.1.0 (int8)",
    languages: "25 European languages",
    size: "about 641 MiB",
    notes: "Optional, added in v0.18.0. Weights licensed CC BY-SA 4.0.",
  },
];

const packages = [
  {
    name: "install.sh / source install",
    parakeet: true,
    note: "Use --engine=parakeet",
  },
  {
    name: "AUR (vocalinux)",
    parakeet: true,
    note: "Listed as an optional dependency: python-sherpa-onnx",
  },
  {
    name: "AppImage (and AUR vocalinux-bin)",
    parakeet: false,
    note: "Ships whisper.cpp only",
  },
  { name: "Flatpak", parakeet: false, note: "Ships whisper.cpp only" },
  { name: "Snap", parakeet: false, note: "Ships whisper.cpp only" },
  {
    name: ".deb / .rpm",
    parakeet: false,
    note: "Thin packages; whisper.cpp on CPU",
  },
  {
    name: "Nix flake",
    parakeet: false,
    note: "Parakeet extra is not packaged",
  },
];

const comparison = [
  {
    topic: "Runtime",
    parakeet: "sherpa-onnx running NVIDIA NeMo transducer models",
    whisperCpp: "whisper.cpp through pywhispercpp",
  },
  {
    topic: "Hardware",
    parakeet: "CPU",
    whisperCpp: "Vulkan (AMD, Intel, NVIDIA), CUDA, or CPU",
  },
  {
    topic: "Languages",
    parakeet: "25 European languages (v3) or English (v2)",
    whisperCpp: "Full language catalog plus Auto-detect",
  },
  {
    topic: "Language picker",
    parakeet: "Ignored; language is treated as auto",
    whisperCpp: "Used, including Follow keyboard layout",
  },
  {
    topic: "Model choice",
    parakeet: "Three models of roughly the same size",
    whisperCpp: "Tiny to Large v3, with quantized and .en variants",
  },
  {
    topic: "Custom dictionary terms",
    parakeet: "Not applied (corrections still work)",
    whisperCpp: "Terms bias recognition; corrections work",
  },
  {
    topic: "Packages",
    parakeet: "install.sh, source, AUR optional dependency",
    whisperCpp: "Every package",
  },
];

const faqs = [
  {
    question: "Is Parakeet better than whisper.cpp?",
    answer:
      "It depends on your languages and hardware. Parakeet is a strong CPU option if you dictate in English or one of the 25 European languages its v3 model covers. whisper.cpp stays the default because it covers the whole language catalog, can use a Vulkan or CUDA GPU, and ships in every package. Try both on your own voice and machine.",
  },
  {
    question: "Does Parakeet send my audio anywhere?",
    answer:
      "No. Parakeet is a local engine. After the model download, recognition runs on your machine and audio is not sent to a server. Only the Remote API engine and VocaGateway send audio to an endpoint you configure.",
  },
  {
    question: "Why is the Language picker greyed out or ignored with Parakeet?",
    answer:
      "Parakeet's language coverage comes from the model, not from the Vocalinux language catalog. Vocalinux treats the language as auto for Parakeet, so pick v2-english for English only or v3-european for the European set. Follow keyboard layout is not available for Parakeet.",
  },
  {
    question: "Can I use Parakeet from the AppImage, Flatpak or Snap?",
    answer:
      "No. Those packages ship whisper.cpp only. Use the install.sh installer or a source install with --engine=parakeet, or the AUR package with python-sherpa-onnx installed.",
  },
  {
    question: "What is Orukeet?",
    answer:
      "Orukeet v0.1.0 is an optional model for the Parakeet engine, added in v0.18.0. It runs on the same local sherpa-onnx recognizer, covers 25 European languages, takes about 641 MiB, and its weights are licensed CC BY-SA 4.0. Vocalinux downloads it from a pinned Hugging Face revision and checks every file against bundled SHA-256 pins.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Parakeet Speech Recognition on Linux | Vocalinux",
  description:
    "Run NVIDIA Parakeet TDT speech recognition offline on Linux with Vocalinux: install, pick v3-european, v2-english or Orukeet, languages, packages and fixes.",
  path: "/parakeet",
  keywords: [
    "Parakeet speech recognition Linux",
    "Parakeet TDT 0.6B Linux",
    "NVIDIA Parakeet offline dictation",
    "sherpa-onnx Parakeet",
    "Orukeet model",
    "Parakeet vs whisper.cpp",
    "offline voice typing Linux CPU",
  ],
});

export default function ParakeetPage() {
  const jsonLd = [
    {
      "@context": "https://schema.org",
      "@type": "TechArticle",
      headline: "Parakeet speech recognition on Linux",
      description:
        "How to install and use the Parakeet speech engine in Vocalinux on Linux, including model variants, languages, package availability and troubleshooting.",
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
      mainEntityOfPage: absoluteUrl("/parakeet"),
    },
    {
      "@context": "https://schema.org",
      "@type": "HowTo",
      name: "Set up the Parakeet engine in Vocalinux",
      step: setupSteps.map((step, index) => ({
        "@type": "HowToStep",
        position: index + 1,
        name: step.title,
        text: step.text,
      })),
    },
    {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: faqs.map((faq) => ({
        "@type": "Question",
        name: faq.question,
        acceptedAnswer: { "@type": "Answer", text: faq.answer },
      })),
    },
  ];

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <section>
        <p className="subpage-kicker">
          <Cpu className="h-4 w-4" aria-hidden="true" />
          Added in v0.17.0
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Parakeet speech recognition on Linux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Parakeet is an optional local speech engine in Vocalinux. It runs
          NVIDIA&apos;s Parakeet TDT 0.6B models on your CPU through sherpa-onnx
          and types what you say into the focused app, with no cloud
          transcription. It suits people who dictate in English or a European
          language and want a CPU engine with a short list of models to choose
          from.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-3">
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Lock className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <p className="mb-2 font-semibold text-foreground">On-device</p>
          <p className="text-sm text-muted-foreground">
            After the one-time model download, recognition runs locally. Audio
            stays on your machine.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Globe className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <p className="mb-2 font-semibold text-foreground">
            25 European languages
          </p>
          <p className="text-sm text-muted-foreground">
            The default v3-european model covers 25 European languages.
            v2-english is English only.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Download className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <p className="mb-2 font-semibold text-foreground">
            Verified downloads
          </p>
          <p className="text-sm text-muted-foreground">
            Models come from pinned Hugging Face revisions and are checked
            against SHA-256 pins before loading.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          What is Parakeet?
        </h2>
        <div className="max-w-4xl space-y-4 text-muted-foreground">
          <p>
            Parakeet is a family of automatic speech recognition models from
            NVIDIA&apos;s NeMo toolkit. Vocalinux uses the TDT 0.6B models,
            which are transducer models: they turn audio straight into text
            tokens rather than generating text the way Whisper does. Vocalinux
            loads int8 ONNX exports of these models with{" "}
            <a
              href="https://github.com/k2-fsa/sherpa-onnx"
              className="text-primary underline"
              rel="noopener noreferrer"
            >
              sherpa-onnx
            </a>
            , a speech runtime that runs on an ordinary CPU.
          </p>
          <p>
            Parakeet arrived in Vocalinux v0.17.0 alongside Faster Whisper.
            whisper.cpp is still the default engine; Parakeet is something you
            opt into.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">
          Install and select Parakeet
        </h2>
        <div className="mb-6 rounded-lg bg-[color:var(--terminal)] p-4">
          {installCommands.map((command) => (
            <code
              key={command}
              className="block text-sm text-[color:var(--terminal-fg)]"
            >
              {command}
            </code>
          ))}
        </div>
        <ol className="space-y-4">
          {setupSteps.map((step, index) => (
            <li
              key={step.title}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <div className="mb-2 flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {index + 1}
                </span>
                <h3 className="font-semibold">{step.title}</h3>
              </div>
              <p className="ml-10 text-sm text-muted-foreground">{step.text}</p>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-sm text-muted-foreground">
          To start once with Parakeet from a terminal, run{" "}
          <code className="rounded bg-muted px-1">
            vocalinux --engine parakeet
          </code>
          . In{" "}
          <code className="rounded bg-muted px-1">
            ~/.config/vocalinux/config.json
          </code>{" "}
          the engine name is{" "}
          <code className="rounded bg-muted px-1">parakeet</code>.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Parakeet models and Orukeet
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          The Model size picker lists three models for the Parakeet engine.
          Sizes are the catalog values Vocalinux shows before a download.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Model ID</th>
                <th className="pb-3 pr-4 font-semibold">Model</th>
                <th className="pb-3 pr-4 font-semibold">Languages</th>
                <th className="pb-3 pr-4 font-semibold">Download</th>
                <th className="pb-3 font-semibold">Notes</th>
              </tr>
            </thead>
            <tbody>
              {models.map((model) => (
                <tr key={model.id} className="border-b border-border">
                  <td className="py-3 pr-4 font-mono text-xs">{model.id}</td>
                  <td className="py-3 pr-4">{model.name}</td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {model.languages}
                  </td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {model.size}
                  </td>
                  <td className="py-3 text-muted-foreground">{model.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 mt-6 font-semibold">
          About the optional Orukeet model
        </h3>
        <p className="text-sm text-muted-foreground">
          Orukeet v0.1.0 was added in v0.18.0. It uses the same local
          sherpa-onnx recognizer and covers 25 European languages; the
          recommended Parakeet model and the default whisper.cpp engine are
          unchanged. Vocalinux downloads it from a pinned revision of{" "}
          <a
            href="https://huggingface.co/oruk/orukeet"
            className="text-primary underline"
            rel="noopener noreferrer"
          >
            oruk/orukeet on Hugging Face
          </a>
          , checks every file against bundled SHA-256 pins, and checks the
          publisher&apos;s release manifest against those same pins. Its CC
          BY-SA 4.0 weights license and NVIDIA attribution are saved with the
          model.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">Languages</h2>
        <div className="max-w-4xl space-y-4 text-muted-foreground">
          <p>
            With Parakeet, the model decides the language, not the Language
            picker. Vocalinux treats the language as auto for this engine, so a
            language you chose for whisper.cpp is not passed to Parakeet. Choose
            v2-english if you only speak English, or v3-european (or Orukeet)
            for the 25-language European set.
          </p>
          <p>
            Two related features do not apply to Parakeet:{" "}
            <strong>Follow keyboard layout</strong> works with whisper.cpp,
            Whisper, Faster Whisper and the Remote API only, and custom
            dictionary <em>terms</em> bias only the Whisper-family engines.
            Transcript corrections from the custom dictionary do run after
            Parakeet. See{" "}
            <Link href="/languages/" className="text-primary underline">
              languages by engine
            </Link>
            ,{" "}
            <Link
              href="/multilingual-dictation/"
              className="text-primary underline"
            >
              multilingual dictation
            </Link>{" "}
            and{" "}
            <Link href="/custom-dictionary/" className="text-primary underline">
              custom dictionary
            </Link>
            .
          </p>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Hardware and packages
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Parakeet runs on the CPU. Vocalinux&apos;s Vulkan and CUDA
          acceleration applies to whisper.cpp, so a GPU does not speed up
          Parakeet (see{" "}
          <Link href="/gpu-acceleration/" className="text-primary underline">
            GPU acceleration
          </Link>
          ). Plan for roughly 640 MB of disk per Parakeet model, stored under{" "}
          <code className="rounded bg-muted px-1">
            ~/.local/share/vocalinux/models/
          </code>
          .
        </p>
        <h3 className="mb-3 font-semibold">Which packages include Parakeet</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Install method</th>
                <th className="pb-3 pr-4 font-semibold">Parakeet</th>
                <th className="pb-3 font-semibold">Notes</th>
              </tr>
            </thead>
            <tbody>
              {packages.map((pkg) => (
                <tr key={pkg.name} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{pkg.name}</td>
                  <td className="py-3 pr-4">
                    {pkg.parakeet ? (
                      <span className="inline-flex items-center gap-1.5 text-primary">
                        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                        Yes
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                        <XCircle className="h-4 w-4" aria-hidden="true" />
                        No
                      </span>
                    )}
                  </td>
                  <td className="py-3 text-muted-foreground">{pkg.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Parakeet vs whisper.cpp
        </h2>
        <p className="mb-4 max-w-4xl text-muted-foreground">
          Both are local engines. The differences are about languages, hardware
          and packaging rather than a single winner. For every engine side by
          side, see the{" "}
          <Link href="/compare/" className="text-primary underline">
            engine comparison
          </Link>
          ; for whisper.cpp sizes, see the{" "}
          <Link href="/whisper-model-guide/" className="text-primary underline">
            Whisper model guide
          </Link>
          .
        </p>
        <div className="overflow-x-auto rounded-[12px] border border-border bg-background p-6">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">
                  <span className="sr-only">Topic</span>
                </th>
                <th className="pb-3 pr-4 font-semibold">Parakeet</th>
                <th className="pb-3 font-semibold">whisper.cpp</th>
              </tr>
            </thead>
            <tbody>
              {comparison.map((row) => (
                <tr key={row.topic} className="border-b border-border">
                  <th scope="row" className="py-3 pr-4 font-medium">
                    {row.topic}
                  </th>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.parakeet}
                  </td>
                  <td className="py-3 text-muted-foreground">
                    {row.whisperCpp}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 max-w-4xl text-sm text-muted-foreground">
          Pick Parakeet if you dictate in English or a supported European
          language on a CPU-only machine and installed with install.sh, from
          source or from the AUR. Stay on whisper.cpp if you use a language
          outside that set, want GPU acceleration, rely on custom dictionary
          terms, or installed the AppImage, Flatpak, Snap, .deb or .rpm.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Troubleshooting
        </h2>
        <div className="space-y-5 text-sm text-muted-foreground">
          <div>
            <h3 className="mb-1 font-semibold text-foreground">
              Parakeet is missing from the Engine list
            </h3>
            <p>
              Settings lists only engines whose libraries are installed.
              Parakeet appears once sherpa-onnx can be imported. Re-run the
              installer with{" "}
              <code className="rounded bg-muted px-1">--engine=parakeet</code>.
              Installs of this engine through install.sh were broken before
              v0.18.4, so use a current installer; on Arch, install
              python-sherpa-onnx.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-foreground">
              The model will not load after an interrupted download
            </h3>
            <p>
              Vocalinux refuses to load Parakeet files that fail checksum
              verification. In Settings → Speech Model, delete the leftover
              model from <strong>Unused downloads</strong> and download it
              again.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-foreground">
              Text comes out in the wrong language
            </h3>
            <p>
              The Language picker does not steer Parakeet. If you only dictate
              English, switch the model to v2-english. For a language outside
              the European set, use whisper.cpp.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-foreground">
              Anything else
            </h3>
            <p>
              Run{" "}
              <code className="rounded bg-muted px-1">vocalinux --debug</code>{" "}
              and check{" "}
              <code className="rounded bg-muted px-1">
                ~/.local/share/vocalinux/vocalinux.log
              </code>
              , then see the{" "}
              <Link href="/troubleshooting/" className="text-primary underline">
                troubleshooting guide
              </Link>
              .
            </p>
          </div>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">
          Parakeet FAQ
        </h2>
        <div className="space-y-4">
          {faqs.map((faq) => (
            <div
              key={faq.question}
              className="rounded-[12px] border border-border bg-background p-5"
            >
              <h3 className="mb-2 font-semibold">{faq.question}</h3>
              <p className="text-sm text-muted-foreground">{faq.answer}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Try Parakeet on your machine
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux with the Parakeet engine, or start with whisper.cpp
          and compare. Also see{" "}
          <Link href="/faster-whisper/" className="text-primary underline">
            Faster Whisper on Linux
          </Link>
          , the other CPU engine added in v0.17.0.
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
            href="/compare/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Compare engines
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
