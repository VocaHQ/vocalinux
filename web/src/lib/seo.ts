import { type Metadata } from "next";

export const SITE_URL = "https://vocalinux.com";
export const SITE_NAME = "Vocalinux";
export const DEFAULT_OG_IMAGE_PATH = "/og-image.png";
export const DEFAULT_OG_IMAGE_ALT =
  "Dictate locally. In any app. Offline voice dictation for Linux.";
export const TWITTER_HANDLE = "@vocahq";
export const VOCAHQ_URL = "https://vocahq.com";
export const GITHUB_REPO_URL = "https://github.com/VocaHQ/vocalinux";
export const X_URL = "https://x.com/vocahq";
export const DISCORD_URL = "https://discord.gg/t6muquAJbm";
export const EMAIL_URL = "mailto:hello@vocahq.com";

// Structured-data identity for the author and the publisher. The Person @id
// matches the one on jatinkrmalik.com/about/ so search engines merge the two
// descriptions into one entity; the Wikidata links anchor both.
export const AUTHOR_PERSON_ID = "https://jatinkrmalik.com/about/#person";

export const AUTHOR_PERSON = {
  "@type": "Person",
  "@id": AUTHOR_PERSON_ID,
  name: "Jatin K Malik",
  alternateName: "Jatin Kumar Malik",
  url: "https://jatinkrmalik.com/",
  sameAs: [
    "https://www.wikidata.org/wiki/Q142178778",
    "https://jatinkrmalik.com/about/",
    "https://github.com/jatinkrmalik",
    "https://x.com/jatinkrmalik",
    "https://www.linkedin.com/in/jatinkrmalik/",
  ],
};

export const AUTHOR_PERSON_REF = { "@id": AUTHOR_PERSON_ID };

export const VOCAHQ_ORGANIZATION = {
  "@type": "Organization",
  "@id": "https://vocahq.com/#organization",
  name: "VocaHQ",
  url: "https://vocahq.com/",
  sameAs: [
    "https://www.wikidata.org/wiki/Q142179028",
    "https://github.com/VocaHQ",
  ],
};

export const VOCALINUX_WIKIDATA_URL =
  "https://www.wikidata.org/wiki/Q142178915";

interface PageMetadataOptions {
  title: string;
  description: string;
  path?: string;
  keywords?: string[];
}

const normalizePath = (path: string): string => {
  if (path === "/") {
    return "/";
  }

  const trimmed = path.replace(/^\/+|\/+$/g, "");

  // Files such as /vocalinux.png must not get the page trailing slash:
  // /vocalinux.png/ is a 404 on GitHub Pages.
  if (/\.[a-z0-9]+$/i.test(trimmed)) {
    return `/${trimmed}`;
  }

  return `/${trimmed}/`;
};

export const absoluteUrl = (path = "/"): string => {
  return new URL(normalizePath(path), SITE_URL).toString();
};

export const buildPageMetadata = ({
  title,
  description,
  path = "/",
  keywords = [],
}: PageMetadataOptions): Metadata => {
  const canonical = absoluteUrl(path);

  // The root layout applies the "%s | Vocalinux" template. Titles that already
  // carry the brand suffix are emitted as-is so search results do not show
  // "| Vocalinux | Vocalinux".
  const pageTitle: Metadata["title"] = new RegExp(
    `[|\\-–—]\\s*${SITE_NAME}$`,
  ).test(title)
    ? { absolute: title }
    : title;

  return {
    title: pageTitle,
    description,
    keywords,
    alternates: {
      canonical,
      languages: {
        "en-US": canonical,
      },
    },
    openGraph: {
      type: "website",
      locale: "en_US",
      siteName: SITE_NAME,
      url: canonical,
      title,
      description,
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
      title,
      description,
      images: [DEFAULT_OG_IMAGE_PATH],
      creator: TWITTER_HANDLE,
      site: TWITTER_HANDLE,
    },
  };
};
