import "@/styles/globals.css";
import React from "react";
import { Bricolage_Grotesque, Source_Sans_3 } from "next/font/google";
import { type Metadata } from "next";
import Script from "next/script";
import { ThemeProvider } from "@/components/theme-provider";
import {
  absoluteUrl,
  DEFAULT_OG_IMAGE_ALT,
  DEFAULT_OG_IMAGE_PATH,
  GITHUB_REPO_URL,
  SITE_NAME,
  SITE_URL,
  TWITTER_HANDLE,
  VOCAHQ_URL,
} from "@/lib/seo";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const body = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0c0c0e" },
  ],
};

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Vocalinux: Offline Voice Dictation for Linux",
    template: "%s | Vocalinux",
  },
  description:
    "Free and open-source voice dictation for Linux. Convert speech to text with whisper.cpp, VOSK, Remote API servers, Silero VAD, X11, and Wayland.",
  applicationName: SITE_NAME,
  keywords: [
    "voice dictation linux",
    "speech to text linux",
    "offline voice dictation",
    "linux voice typing",
    "whisper.cpp linux",
    "vosk linux",
    "remote api speech recognition",
    "silero vad linux",
    "whisper.cpp advanced settings",
    "ibus voice dictation",
    "wayland voice dictation",
    "x11 speech recognition",
    "open source dictation software",
    "voice typing ubuntu",
    "voice typing fedora",
    "voice typing arch linux",
  ],
  authors: [{ name: "Jatin K Malik", url: "https://github.com/jatinkrmalik" }],
  creator: "Jatin K Malik",
  publisher: SITE_NAME,
  icons: {
    icon: [
      { url: "/vocalinux.png", type: "image/png" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-96x96.png", sizes: "96x96", type: "image/png" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
    shortcut: "/vocalinux.png",
  },
  manifest: "/site.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: SITE_NAME,
  },
  formatDetection: {
    telephone: false,
    email: false,
    address: false,
  },
  referrer: "strict-origin-when-cross-origin",
  openGraph: {
    type: "website",
    locale: "en_US",
    url: absoluteUrl("/"),
    siteName: SITE_NAME,
    title: "Vocalinux: Offline Voice Dictation for Linux",
    description:
      "Voice dictation for Linux that runs fully offline. Install in minutes and dictate in any app on Ubuntu, Fedora, Arch, X11, or Wayland.",
    images: [
      {
        url: DEFAULT_OG_IMAGE_PATH,
        width: 1200,
        height: 630,
        alt: DEFAULT_OG_IMAGE_ALT,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Vocalinux: Offline Voice Dictation for Linux",
    description:
      "Speech-to-text for Linux with whisper.cpp and VOSK. 100% offline, privacy-first, and open-source.",
    images: [DEFAULT_OG_IMAGE_PATH],
    creator: TWITTER_HANDLE,
    site: TWITTER_HANDLE,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  alternates: {
    canonical: absoluteUrl("/"),
    languages: {
      "en-US": absoluteUrl("/"),
    },
  },
  category: "Technology",
};

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": `${absoluteUrl("/")}#organization`,
  name: SITE_NAME,
  url: absoluteUrl("/"),
  logo: absoluteUrl("/vocalinux.png"),
  description: "Open-source, offline voice dictation software for Linux.",
  sameAs: [GITHUB_REPO_URL, VOCAHQ_URL],
  founder: {
    "@type": "Person",
    name: "Jatin K Malik",
    url: "https://github.com/jatinkrmalik",
  },
  parentOrganization: {
    "@type": "Organization",
    name: "VocaHQ",
    url: VOCAHQ_URL,
  },
};

const webSiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": `${absoluteUrl("/")}#website`,
  name: SITE_NAME,
  url: absoluteUrl("/"),
  inLanguage: "en-US",
  description:
    "Vocalinux provides offline speech-to-text and voice dictation for Linux desktops.",
  publisher: {
    "@id": `${absoluteUrl("/")}#organization`,
  },
  potentialAction: {
    "@type": "SearchAction",
    target: {
      "@type": "EntryPoint",
      urlTemplate:
        `${GITHUB_REPO_URL}/issues?q={search_term_string}`,
    },
    "query-input": {
      "@type": "PropertyValueSpecification",
      valueRequired: true,
      valueName: "search_term_string",
    },
  },
};

const siteWideJsonLd = [organizationJsonLd, webSiteJsonLd];

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} scroll-smooth`}
      suppressHydrationWarning
    >
      <head>
        <link rel="preconnect" href="https://api.github.com" />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(siteWideJsonLd) }}
        />
      </head>
      <body>
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-7NBBNJNNQ7"
          strategy="lazyOnload"
        />
        <Script id="google-analytics" strategy="lazyOnload">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', 'G-7NBBNJNNQ7');
          `}
        </Script>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
