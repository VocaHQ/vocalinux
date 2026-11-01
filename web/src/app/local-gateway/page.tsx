import Link from "next/link";
import { type Metadata } from "next";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ChevronRight,
  ExternalLink,
  Lock,
  Server,
} from "lucide-react";
import { SeoSubpageShell } from "@/components/seo-subpage-shell";
import { absoluteUrl, buildPageMetadata } from "@/lib/seo";

const PAGE_PATH = "/local-gateway";
const PAGE_TITLE = "Run a Local VocaGateway for Linux Dictation";
const PAGE_DESCRIPTION =
  "Start a local VocaGateway from Vocalinux Settings with podman or docker, connect it via Remote API, and learn why gateway mode is not on-device transcription.";

const comparisonRows = [
  {
    mode: "Local engine (default whisper.cpp)",
    audio: "Stays on this machine; transcribed in the app",
    setup: "Download a model once",
    network: "None for transcription",
  },
  {
    mode: "Local VocaGateway on 127.0.0.1",
    audio: "Sent over HTTP to the gateway container on this machine",
    setup: "podman or docker with Compose",
    network: "Loopback only by default",
  },
  {
    mode: "Gateway or Remote API on another machine",
    audio: "Leaves this machine for the endpoint you configured",
    setup: "Server URL and token in Remote Server",
    network: "Your LAN, VPN or the internet",
  },
];

const statusRows = [
  { status: "Stopped", meaning: "Not running." },
  {
    status: "Starting",
    meaning: "Compose up in progress, or the live probe is not green yet.",
  },
  { status: "Live", meaning: "The gateway answers /health/live." },
  {
    status: "Pairable",
    meaning:
      "Live, plus a non-loopback phone URL and bearer token for pairing.",
  },
  {
    status: "Ready",
    meaning: "/health/ready returns 200 (a model is selected in the gateway).",
  },
  {
    status: "Error",
    meaning: "Start, stop or probe failure; the subtitle says which.",
  },
];

const steps = [
  {
    name: "Open the Advanced section",
    text: "Open Settings → Speech Model and expand Advanced. The Local VocaGateway group sits next to Remote Server.",
  },
  {
    name: "Run the gateway",
    text: "Click Run VocaGateway locally. The first start builds the local image vocagateway:v0.1.0 from the pinned tag, so it takes longer than later starts.",
  },
  {
    name: "Wait for Ready",
    text: "Watch the Status row. Select a model in the gateway's own web UI; the status shows Ready once the gateway reports it can transcribe.",
  },
  {
    name: "Use this Gateway",
    text: "Click Use this Gateway. Vocalinux fills Remote Server with the gateway URL and bearer token, sets the endpoint to /v1/audio/transcriptions and switches the engine to Remote API.",
  },
  {
    name: "Dictate and verify",
    text: "Use Test Connection in Remote Server, then dictate as usual with your normal shortcut.",
  },
];

const faqs = [
  {
    question: "Is a local gateway the same as on-device dictation?",
    answer:
      "No. Even on 127.0.0.1, audio leaves the Vocalinux client and is transcribed by a separate gateway process over HTTP. The on-device path is a local engine such as whisper.cpp, which stays the default.",
  },
  {
    question: "Does quitting Vocalinux stop the gateway?",
    answer:
      "No. The pinned compose file uses restart: unless-stopped, so the container keeps running after Quit. Use Stop local Gateway in Settings or the tray menu.",
  },
  {
    question: "Can I run it from the Flatpak?",
    answer:
      "No. The Flatpak sandbox cannot reach the host podman or docker socket. Use the native package or AppImage, or start VocaGateway on the host yourself and point Remote Server at it.",
  },
  {
    question: "Do I need a Voca account?",
    answer:
      "No. VocaGateway is optional self-hosted software. There is no Voca account and no hosted Voca cloud.",
  },
  {
    question: "How do I go back to on-device transcription?",
    answer:
      "Choose a local engine again under Speech Engine in Settings → Speech Model → Advanced. Stop the gateway too if you no longer need it.",
  },
];

export const metadata: Metadata = buildPageMetadata({
  title: `${PAGE_TITLE} | Vocalinux`,
  description: PAGE_DESCRIPTION,
  path: PAGE_PATH,
  keywords: [
    "vocagateway linux",
    "local speech gateway podman",
    "self hosted dictation gateway",
    "vocalinux remote api gateway",
    "docker speech to text linux dictation",
    "phone dictation gateway linux",
  ],
});

function InlineCode({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground">
      {children}
    </code>
  );
}

export default function LocalGatewayPage() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "TechArticle",
        headline: PAGE_TITLE,
        description: PAGE_DESCRIPTION,
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
      },
      {
        "@type": "HowTo",
        name: "Run a local VocaGateway from Vocalinux Settings",
        step: steps.map((step, index) => ({
          "@type": "HowToStep",
          position: index + 1,
          name: step.name,
          text: step.text,
        })),
      },
      {
        "@type": "FAQPage",
        mainEntity: faqs.map((faq) => ({
          "@type": "Question",
          name: faq.question,
          acceptedAnswer: { "@type": "Answer", text: faq.answer },
        })),
      },
    ],
  };

  return (
    <SeoSubpageShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <section>
        <p className="subpage-kicker">Added in v0.18.0 · optional</p>
        <h1 className="mb-5 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
          Run a local VocaGateway from Vocalinux
        </h1>
        <p className="mb-6 max-w-4xl text-lg text-muted-foreground">
          Vocalinux can start{" "}
          <a
            href="https://vocagateway.vocahq.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline"
          >
            VocaGateway
          </a>
          , the self-hosted speech gateway in the Voca family, as a podman or
          docker container from its own Settings. It is a power-user path for
          people who want one transcription service shared by the desktop and a
          paired phone.
        </p>
      </section>

      <section className="bg-primary/5 mb-12 rounded-[12px] border border-border p-6">
        <h2 className="mb-3 flex items-center gap-2 text-xl font-semibold">
          <Lock className="h-5 w-5 text-primary" aria-hidden="true" />
          Gateway mode is not the on-device engine
        </h2>
        <p className="text-sm text-muted-foreground">
          With a local engine, audio is transcribed on this machine by Vocalinux
          itself. In gateway mode it is sent over HTTP to the gateway, even when
          that gateway runs on <InlineCode>127.0.0.1</InlineCode>. If you point
          Vocalinux at a gateway on another machine, your audio leaves this
          machine for that endpoint. Keep it on a trusted LAN, an encrypted
          private network such as Tailscale, or HTTPS, and never expose port
          8765 to the public internet. Enabling the gateway does not change the
          default engine; whisper.cpp stays on-device until you click Use this
          Gateway.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Where your audio goes
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Mode
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Audio
                </th>
                <th scope="col" className="pb-3 pr-4 font-semibold">
                  Setup
                </th>
                <th scope="col" className="pb-3 font-semibold">
                  Network
                </th>
              </tr>
            </thead>
            <tbody>
              {comparisonRows.map((row) => (
                <tr key={row.mode} className="border-b border-border align-top">
                  <th scope="row" className="py-3 pr-4 font-medium">
                    {row.mode}
                  </th>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.audio}
                  </td>
                  <td className="py-3 pr-4 text-muted-foreground">
                    {row.setup}
                  </td>
                  <td className="py-3 text-muted-foreground">{row.network}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <Server className="h-5 w-5 text-primary" aria-hidden="true" />
          Requirements
        </h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            podman (preferred) or docker, with a working Compose plugin, or{" "}
            <InlineCode>podman-compose</InlineCode> /{" "}
            <InlineCode>docker-compose</InlineCode>. If the engine is present
            but Compose is missing, Settings tells you which to install.
          </li>
          <li>
            A native install or the AppImage. The AppImage does not bundle a
            container engine; it uses the host&apos;s podman or docker socket
            when available.
          </li>
          <li>
            Not the Flatpak: its sandbox cannot reach the host container socket,
            so the controls are blocked there.
          </li>
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">Set it up</h2>
        <ol className="space-y-4">
          {steps.map((step, index) => (
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
        <h3 className="mb-2 mt-6 font-semibold">Status labels</h3>
        <div className="overflow-x-auto rounded-[12px] border border-border bg-background p-5">
          <table className="w-full text-left text-sm">
            <tbody>
              {statusRows.map((row) => (
                <tr
                  key={row.status}
                  className="border-b border-border last:border-0"
                >
                  <th scope="row" className="py-2 pr-4 font-medium">
                    {row.status}
                  </th>
                  <td className="py-2 text-muted-foreground">{row.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          Pairable can appear before Ready, so a phone can pair while a model is
          still downloading.
        </p>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          What Vocalinux sets up
        </h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            A checkout of VocaGateway pinned to the{" "}
            <InlineCode>v0.1.0</InlineCode> tag under your XDG cache, run as the
            Compose project <InlineCode>vocagateway</InlineCode> with the{" "}
            <InlineCode>cpu</InlineCode> profile. It never floats on{" "}
            <InlineCode>latest</InlineCode>;{" "}
            <InlineCode>VOCAGATEWAY_IMAGE</InlineCode> overrides the image.
          </li>
          <li>
            A private bootstrap token in{" "}
            <InlineCode>~/.config/vocalinux/gateway_embed/</InlineCode> with
            mode 600, plus a matching Compose <InlineCode>.env</InlineCode>.
          </li>
          <li>
            A port published on <InlineCode>127.0.0.1:8765</InlineCode> by
            default, reachable from this desktop only.
          </li>
          <li>
            The usual Remote API settings. Use this Gateway writes the URL,
            token, endpoint and the model name{" "}
            <InlineCode>whisper-1</InlineCode> into the same{" "}
            <InlineCode>remote_api_*</InlineCode> keys described on the{" "}
            <Link href="/remote-api/" className="text-primary underline">
              Remote API page
            </Link>
            . The token is stored in plain JSON in{" "}
            <InlineCode>config.json</InlineCode>, like any Remote API key.
          </li>
        </ul>
      </section>

      <section className="mb-12 rounded-[12px] border border-border bg-background p-6">
        <h2 className="mb-4 flex items-center gap-2 font-display text-2xl font-semibold">
          <AlertTriangle className="h-5 w-5 text-primary" aria-hidden="true" />
          LAN access, stopping and gotchas
        </h2>
        <h3 className="mb-2 font-semibold">Allow LAN access for Phone</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          This switch publishes the gateway on{" "}
          <InlineCode>0.0.0.0:8765</InlineCode> and advertises a LAN URL for
          phone pairing. Open port 8765 in your firewall only on networks you
          trust. If the switch fails, Compose keeps the previous bind and the
          switch snaps back with an error; stop and run again, or retry.
        </p>
        <h3 className="mb-2 font-semibold">Quit does not stop it</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          The container keeps running after you quit Vocalinux, including a
          LAN-published one. Use Stop local Gateway in Settings or the tray
          menu, which appears whenever Compose is running. Stopping keeps the
          named data volume, so downloaded models survive. Vocalinux does not
          start the gateway on login.
        </p>
        <h3 className="mb-2 font-semibold">Other machines</h3>
        <p className="text-sm text-muted-foreground">
          You can also run VocaGateway on a stronger box and enter its address
          in Remote Server by hand. Audio then crosses your network, so prefer a
          trusted LAN, Tailscale or HTTPS. Read the{" "}
          <a
            href="https://vocagateway.vocahq.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-primary underline"
          >
            VocaGateway documentation
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>{" "}
          for server-side setup.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-semibold">FAQ</h2>
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
        <p className="mt-4 text-sm text-muted-foreground">
          Related:{" "}
          <Link href="/offline/" className="text-primary underline">
            offline dictation
          </Link>
          ,{" "}
          <Link href="/privacy/" className="text-primary underline">
            privacy
          </Link>
          ,{" "}
          <Link href="/flatpak/" className="text-primary underline">
            Flatpak limitations
          </Link>{" "}
          and{" "}
          <Link href="/gpu-acceleration/" className="text-primary underline">
            GPU acceleration
          </Link>{" "}
          for faster on-device engines.
        </p>
      </section>

      <section className="rounded-[12px] border border-border bg-muted p-8">
        <h2 className="mb-4 font-display text-2xl font-semibold">
          Start on-device, add a gateway later
        </h2>
        <p className="mb-6 text-muted-foreground">
          Install Vocalinux with the default on-device engine. Add a local
          VocaGateway only if you need a shared transcription service.
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
            href="/remote-api/"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold hover:bg-muted"
          >
            Remote API settings
          </Link>
        </div>
      </section>
    </SeoSubpageShell>
  );
}
