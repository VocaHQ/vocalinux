import { type Metadata } from "next";

export const SITE_URL = "https://vocalinux.com";
export const SITE_NAME = "Vocalinux";
export const DEFAULT_OG_IMAGE_PATH = "/og-image.png";
export const DEFAULT_OG_IMAGE_ALT =
  "Say it once. Your Linux types. Offline voice dictation for Linux.";
export const TWITTER_HANDLE = "@vocahq";
export const VOCAHQ_URL = "https://vocahq.com";
export const GITHUB_REPO_URL = "https://github.com/VocaHQ/vocalinux";
export const X_URL = "https://x.com/vocahq";
export const DISCORD_URL = "https://discord.gg/t6muquAJbm";
export const EMAIL_URL = "mailto:hello@vocahq.com";

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

  return {
    title,
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
