import fs from "fs";
import path from "path";

describe("SEO Assets", () => {
  const robotsPath = path.join(process.cwd(), "public", "robots.txt");
  const sitemapPath = path.join(process.cwd(), "public", "sitemap.xml");

  let robotsContent: string;
  let sitemapContent: string;

  beforeAll(() => {
    robotsContent = fs.readFileSync(robotsPath, "utf-8");
    sitemapContent = fs.readFileSync(sitemapPath, "utf-8");
  });

  it("contains sitemap reference in robots.txt", () => {
    expect(robotsContent).toContain(
      "Sitemap: https://vocalinux.com/sitemap.xml",
    );
  });

  it("blocks crawler access to technical paths", () => {
    expect(robotsContent).toContain("Disallow: /api/");
    expect(robotsContent).toContain("Disallow: /out/");
  });

  it("does not block Next.js static assets needed for rendering", () => {
    expect(robotsContent).not.toContain("Disallow: /_next/");
  });

  it("does not blanket-block query-string URLs", () => {
    // Blocking all query strings causes GSC "Indexed, though blocked by robots.txt"
    // for pages discovered with UTM/tracking params. Use canonicals instead.
    const disallowRules = robotsContent
      .split("\n")
      .filter((line) => line.trimStart().startsWith("Disallow:"));
    expect(disallowRules.some((line) => /\/\*\?\*/.test(line))).toBe(false);
  });

  it("includes core landing pages in sitemap", () => {
    const expectedUrls = [
      "https://vocalinux.com/",
      "https://vocalinux.com/install/",
      "https://vocalinux.com/install/ubuntu/",
      "https://vocalinux.com/install/fedora/",
      "https://vocalinux.com/install/arch/",
      "https://vocalinux.com/compare/",
      "https://vocalinux.com/remote-api/",
      "https://vocalinux.com/voice-activity-detection/",
      "https://vocalinux.com/advanced-settings/",
      "https://vocalinux.com/desktop-reliability/",
      "https://vocalinux.com/screenshots/",
      "https://vocalinux.com/parakeet/",
      "https://vocalinux.com/faster-whisper/",
      "https://vocalinux.com/dictation-pad/",
      "https://vocalinux.com/transcribe-audio-files/",
      "https://vocalinux.com/custom-dictionary/",
      "https://vocalinux.com/multilingual-dictation/",
      "https://vocalinux.com/pipewire/",
      "https://vocalinux.com/global-shortcuts/",
      "https://vocalinux.com/hyprland-sway/",
      "https://vocalinux.com/local-gateway/",
      "https://vocalinux.com/flatpak/",
      "https://vocalinux.com/install/nixos/",
      "https://vocalinux.com/install/debian/",
      "https://vocalinux.com/install/opensuse/",
      "https://vocalinux.com/install/linux-mint/",
      "https://vocalinux.com/install/pop-os/",
    ];

    expectedUrls.forEach((url) => {
      expect(sitemapContent).toContain(`<loc>${url}</loc>`);
    });
  });

  it("lists every static route in the sitemap exactly once", () => {
    const appDir = path.join(process.cwd(), "src", "app");
    const routes: string[] = [];
    const walk = (dir: string, prefix: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (
          !entry.isDirectory() ||
          entry.name.startsWith("__") ||
          entry.name.startsWith("[")
        ) {
          continue;
        }
        const routePath = `${prefix}/${entry.name}`;
        if (fs.existsSync(path.join(dir, entry.name, "page.tsx"))) {
          routes.push(`https://vocalinux.com${routePath}/`);
        }
        walk(path.join(dir, entry.name), routePath);
      }
    };
    walk(appDir, "");

    const locs = Array.from(
      sitemapContent.matchAll(/<loc>([^<]+)<\/loc>/g),
      (match) => match[1],
    );
    expect(new Set(locs).size).toBe(locs.length);
    routes.forEach((url) => {
      expect(locs).toContain(url);
    });
  });
});
