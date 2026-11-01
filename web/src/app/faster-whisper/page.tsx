import Link from "next/link";
import { type Metadata } from "next";
import {
  CheckCircle2,
  ChevronRight,
  Cpu,
  Download,
  Lock,
  XCircle,
  Zap,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const installCommands = [
  "curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh",
  "bash /tmp/vl.sh --auto --engine=faster_whisper",
];

const setupSteps = [
  {
    title: "Install the Faster Whisper engine",
    text: "Faster Whisper is an optional extra. Run the installer and choose Faster-Whisper in the engine menu, or pass --engine=faster_whisper. If the faster-whisper package fails to install, the installer falls back to whisper.cpp and says so.",
  },
  {
    title: "Open Settings → Speech Model",
    text: "Open Settings and go to Speech Model. Set your Language, then expand Advanced to see the Engine and Model size pickers.",
  },
  {
    title: "Pick Faster Whisper and a size",
    text: "Set Engine to Faster Whisper and choose a Model size. Settings suggests one for your hardware. Picking only selects the model; nothing downloads yet.",
  },
  {
    title: "Confirm the download",
    text: "If the model is not on disk, click Download and confirm. Every file is checked against a pinned checksum before the engine loads it.",
  },
  {
    title: "Dictate",
    text: "Hold your dictation shortcut (Right Alt by default on new installs), speak, and release. Text is typed into the focused app.",
  },
];

const sizes = [
  {
    size: "Tiny",
    ids: "tiny, tiny.en",
    params: "39M",
    desc: "Fastest, lowest accuracy",
  },
  {
    size: "Base",
    ids: "base, base.en",
    params: "74M",
    desc: "Fast, good for basic use",
  },
  {
    size: "Small",
    ids: "small, small.en",
    params: "244M",
    desc: "Balanced speed and accuracy",
  },
  {
    size: "Medium",
    ids: "medium, medium.en",
    params: "769M",
    desc: "High accuracy, slower",
  },
  {
    size: "Large v3",
    ids: "large-v3",
    params: "1550M",
    desc: "Highest accuracy, slower",
  },
];

const packages = [
  {
    name: "install.sh / source install",
    included: true,
    note: "Menu option or --engine=faster_whisper",
  },
  {
    name: "AUR (vocalinux)",
    included: true,
    note: "Listed as an optional dependency: python-faster-whisper",
  },
  {
    name: "AppImage (and AUR vocalinux-bin)",
    included: false,
    note: "Ships whisper.cpp only",
  },
  { name: "Flatpak", included: false, note: "Ships whisper.cpp only" },
  { name: "Snap", included: false, note: "Ships whisper.cpp only" },
  {
    name: ".deb / .rpm",
    included: false,
    note: "Thin packages; whisper.cpp on CPU",
  },
  {
    name: "Nix flake",
    included: false,
    note: "faster_whisper extra is not packaged",
  },
];

const choices = [
  {
    engine: "whisper.cpp",
    pick: "The default. Ships in every package, uses a Vulkan GPU on AMD, Intel and NVIDIA, and offers quantized and English-only variants. Start here.",
  },
  {
    engine: "Faster Whisper",
    pick: "You installed with install.sh, from source or from the AUR and want a Whisper model on a CPU-only machine, running through CTranslate2 instead of whisper.cpp.",
  },
  {
    engine: "Whisper (OpenAI)",
    pick: "You already work with PyTorch and NVIDIA CUDA and accept a much larger install.",
  },
  {
    engine: "VOSK",
    pick: "Older or low-RAM machines. Small models are about 40 MB, with one model per language.",
  },
];

const faqs = [
  {
    question: "Is Faster Whisper the same model as Whisper?",
    answer:
      "It runs the same Whisper model family converted to the CTranslate2 format. Vocalinux downloads those conversions from pinned Hugging Face revisions. The sizes and English-only variants match the Whisper names you already know.",
  },
  {
    question: "Does Faster Whisper use my GPU?",
    answer:
      "On a typical install it runs on the CPU with int8. Vocalinux switches to CUDA with float16 only when PyTorch is installed and reports a CUDA GPU. The installer's Faster Whisper option does not install CUDA. For Vulkan GPU acceleration on AMD, Intel or NVIDIA, use whisper.cpp.",
  },
  {
    question: "Can I change the compute type?",
    answer:
      "There is no setting for it. Vocalinux picks int8 on the CPU and float16 on CUDA automatically.",
  },
  {
    question: "Does audio leave my machine?",
    answer:
      "No. Faster Whisper is a local engine. After the model download, recognition runs on your machine. Only the Remote API engine and VocaGateway send audio to an endpoint you configure.",
  },
  {
    question: "Why is Faster Whisper not in my Engine list?",
    answer:
      "Settings lists only engines whose libraries are installed. The AppImage, Flatpak, Snap, .deb and .rpm packages do not include faster-whisper. Re-run the installer with --engine=faster_whisper, or on Arch install python-faster-whisper.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: "Faster Whisper on Linux: Offline Voice Typing | Vocalinux",
  description:
    "Use Faster Whisper (CTranslate2, int8 on CPU) for offline voice typing on Linux with Vocalinux: install, model sizes, GPU and compute options, and fixes.",
  path: "/faster-whisper",
  keywords: [
    "Faster Whisper Linux",
    "faster-whisper dictation",
    "CTranslate2 Whisper Linux",
    "Faster Whisper vs whisper.cpp",
    "offline Whisper CPU int8",
    "Linux voice typing Whisper",
    "faster-whisper model sizes",
  ],
});

export default function FasterWhisperPage() {
  const jsonLd = [
    {
      "@context": "https://schema.org",
      "@type": "TechArticle",
      headline: "Faster Whisper on Linux",
      description:
        "How to install and use the Faster Whisper speech engine in Vocalinux on Linux, including model sizes, compute options, package availability and troubleshooting.",
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
      mainEntityOfPage: absoluteUrl("/faster-whisper"),
    },
    {
      "@context": "https://schema.org",
      "@type": "HowTo",
      name: "Set up the Faster Whisper engine in Vocalinux",
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
          <Zap className="h-4 w-4" aria-hidden="true" />
          Added in v0.17.0
        </p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Faster Whisper on Linux
        </h1>
        <p className="mb-8 max-w-4xl text-lg text-muted-foreground">
          Faster Whisper is an optional local speech engine in Vocalinux. It
          runs Whisper models through CTranslate2 with int8 quantization on your
          CPU and types what you say into the focused app. It is for people who
          want Whisper models and the full language catalog on a machine without
          a GPU, using a different runtime from the default whisper.cpp.
        </p>
      </section>

      <section className="mb-12 grid gap-4 sm:grid-cols-3">
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Cpu className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <p className="mb-2 font-semibold text-foreground">CPU first</p>
          <p className="text-sm text-muted-foreground">
            int8 on the CPU by default. No PyTorch needed for the CPU path.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Lock className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <p className="mb-2 font-semibold text-foreground">On-device</p>
          <p className="text-sm text-muted-foreground">
            After the one-time model download, recognition runs locally. Audio
            stays on your machine.
          </p>
        </div>
        <div className="rounded-[12px] border border-border bg-background p-5">
          <Download className="mb-3 h-6 w-6 text-primary" aria-hidden="true" />
          <p className="mb-2 font-semibold text-foreground">Pinned models</p>
          <p className="text-sm text-muted-foreground">
            Models load only from checksum-verified local files, never from an
            unpinned upstream revision.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          What is Faster Whisper?
        </h2>
        <div className="max-w-4xl space-y-4 text-muted-foreground">
          <p>
            <a
              href="https://github.com/SYSTRAN/faster-whisper"
              className="text-primary underline"
              rel="noopener noreferrer"
            >
              faster-whisper
            </a>{" "}
            is a reimplementation of OpenAI&apos;s Whisper on top of
            CTranslate2, an inference engine for transformer models. It runs
            converted Whisper models and supports reduced precision such as
            int8, which lowers memory use on the CPU.
          </p>
          <p>
            Vocalinux added Faster Whisper as an optional engine in v0.17.0,
            together with Parakeet. whisper.cpp remains the default. Vocalinux
            stores Faster Whisper models under{" "}
            <code className="rounded bg-muted px-1">
              ~/.local/share/vocalinux/models/
            </code>{" "}
            and checks each file against a pinned checksum before loading it.
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-6 font-display text-2xl font-semibold">
          Install and select Faster Whisper
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
          To start once with Faster Whisper from a terminal, run{" "}
          <code className="rounded bg-muted px-1">
            vocalinux --engine faster_whisper
          </code>
          .
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Model sizes
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          The Model size picker offers these sizes. The <code>.en</code>{" "}
          variants are English only; if your language is English, Settings
          suggests the <code>.en</code> variant of the recommended size. There
          is no <code>large-v3.en</code>.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Size</th>
                <th className="pb-3 pr-4 font-semibold">Model IDs</th>
                <th className="pb-3 pr-4 font-semibold">Parameters</th>
                <th className="pb-3 font-semibold">Description</th>
              </tr>
            </thead>
            <tbody>
              {sizes.map((row) => (
                <tr key={row.size} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{row.size}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{row.ids}</td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.params}
                  </td>
                  <td className="py-3 text-muted-foreground">{row.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="mb-2 mt-6 font-semibold">
          Which size Settings suggests
        </h3>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>CPU only, under 16 GB RAM: Tiny</li>
          <li>CPU only, 16 GB RAM or more: Base</li>
          <li>CUDA GPU detected, under 8 GB RAM: Base</li>
          <li>CUDA GPU detected, 8 GB RAM or more: Small</li>
        </ul>
        <p className="mt-3 text-sm text-muted-foreground">
          The suggestion never changes your model or starts a download. If
          dictation feels slow, go one size down; if it makes too many mistakes
          and speed is fine, go one size up. The{" "}
          <Link href="/whisper-model-guide/" className="text-primary underline">
            Whisper model guide
          </Link>{" "}
          explains the size trade-offs in more depth.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Compute options and GPUs
        </h2>
        <div className="max-w-4xl space-y-4 text-muted-foreground">
          <p>
            Vocalinux chooses the device and precision for you; there is no
            compute-type setting. On the CPU it loads the model with{" "}
            <code className="rounded bg-muted px-1">int8</code>. If PyTorch is
            installed and reports a CUDA GPU, it loads the model on CUDA with{" "}
            <code className="rounded bg-muted px-1">float16</code> instead.
          </p>
          <p>
            The installer&apos;s Faster Whisper option is the CPU CTranslate2
            path and does not install the CUDA toolkit. If you want GPU
            dictation on AMD, Intel or NVIDIA, whisper.cpp with Vulkan is the
            supported route; see{" "}
            <Link href="/gpu-acceleration/" className="text-primary underline">
              GPU acceleration
            </Link>
            .
          </p>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">Languages</h2>
        <p className="max-w-4xl text-muted-foreground">
          Faster Whisper uses the same language catalog as the other Whisper
          engines, including Auto-detect. It also supports{" "}
          <strong>Follow keyboard layout</strong>, which switches the dictation
          language with your active layout, and custom dictionary terms that
          bias recognition toward names and jargon. See{" "}
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
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Package availability
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Install method</th>
                <th className="pb-3 pr-4 font-semibold">Faster Whisper</th>
                <th className="pb-3 font-semibold">Notes</th>
              </tr>
            </thead>
            <tbody>
              {packages.map((pkg) => (
                <tr key={pkg.name} className="border-b border-border">
                  <td className="py-3 pr-4 font-medium">{pkg.name}</td>
                  <td className="py-3 pr-4">
                    {pkg.included ? (
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
          Faster Whisper vs whisper.cpp, Whisper and VOSK
        </h2>
        <p className="mb-4 max-w-4xl text-muted-foreground">
          All four are local engines. Choose by hardware and by how you
          installed Vocalinux. For the full table, see the{" "}
          <Link href="/compare/" className="text-primary underline">
            engine comparison
          </Link>{" "}
          or{" "}
          <Link href="/parakeet/" className="text-primary underline">
            Parakeet
          </Link>{" "}
          for the other CPU engine added in v0.17.0.
        </p>
        <div className="overflow-x-auto rounded-[12px] border border-border bg-background p-6">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-3 pr-4 font-semibold">Engine</th>
                <th className="pb-3 font-semibold">Pick it when</th>
              </tr>
            </thead>
            <tbody>
              {choices.map((row) => (
                <tr key={row.engine} className="border-b border-border">
                  <th scope="row" className="py-3 pr-4 font-medium">
                    {row.engine}
                  </th>
                  <td className="py-3 text-muted-foreground">{row.pick}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Troubleshooting
        </h2>
        <div className="space-y-5 text-sm text-muted-foreground">
          <div>
            <h3 className="mb-1 font-semibold text-foreground">
              The installer finished, but whisper.cpp is selected
            </h3>
            <p>
              If faster-whisper fails to install or import, the installer falls
              back to whisper.cpp. Read the installer output, then re-run it
              with{" "}
              <code className="rounded bg-muted px-1">
                --engine=faster_whisper
              </code>
              .
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-foreground">
              Another language is not recognized
            </h3>
            <p>
              The <code>.en</code> models are English only. Pick the size
              without <code>.en</code>, or set Language to Auto-detect with a
              multilingual model.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-foreground">
              Dictation feels slow
            </h3>
            <p>
              Go one size down. On CPU-only machines, Tiny or Base is the usual
              starting point. Larger sizes take longer per sentence on a CPU.
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
          Faster Whisper FAQ
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
          Try Faster Whisper
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux with the Faster Whisper engine, or keep whisper.cpp
          and switch later from Settings → Speech Model.
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
            href="/whisper-model-guide/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Whisper model guide
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
