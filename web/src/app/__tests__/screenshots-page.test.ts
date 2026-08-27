import fs from "fs";
import path from "path";

/**
 * Structural checks for the screenshots gallery: page source, public assets,
 * nav discoverability, and homepage link. Exercises the real shipped files
 * under web/ rather than re-implementing gallery data in the test.
 */
describe("Screenshots page and assets", () => {
  const webRoot = process.cwd();
  const pagePath = path.join(webRoot, "src/app/screenshots/page.tsx");
  const shellPath = path.join(webRoot, "src/components/seo-subpage-shell.tsx");
  const homePath = path.join(webRoot, "src/app/page.tsx");
  const publicScreenshotsDir = path.join(webRoot, "public/screenshots");
  const darkScreenshotsDir = path.join(publicScreenshotsDir, "dark");

  const expectedAssets = [
    "00-transcription.png",
    "02-system-tray.png",
    "03-log-viewer.png",
    "05-about-view.png",
    "settings-speech-engine.png",
    "settings-recognition.png",
    "settings-audio.png",
    "settings-performance.png",
    "settings-general.png",
    "settings-advanced.png",
  ];

  let pageSource: string;
  let shellSource: string;
  let homeSource: string;

  beforeAll(() => {
    pageSource = fs.readFileSync(pagePath, "utf-8");
    shellSource = fs.readFileSync(shellPath, "utf-8");
    homeSource = fs.readFileSync(homePath, "utf-8");
  });

  it("ships a dedicated /screenshots page module with lightbox gallery", () => {
    expect(fs.existsSync(pagePath)).toBe(true);
    expect(pageSource).toMatch(/export default function ScreenshotsPage/);
    expect(pageSource).toContain('path: "/screenshots"');
    expect(pageSource).toContain("Vocalinux Screenshots");
    expect(pageSource).toContain("ScreenshotGallery");
    const galleryPath = path.join(
      webRoot,
      "src/components/screenshot-gallery.tsx",
    );
    expect(fs.existsSync(galleryPath)).toBe(true);
    const gallerySource = fs.readFileSync(galleryPath, "utf-8");
    expect(gallerySource).toContain('role="dialog"');
    expect(gallerySource).toContain("aria-modal");
    expect(gallerySource).toContain("View larger");
  });

  it("references every public screenshot asset from the page source", () => {
    for (const file of expectedAssets) {
      const assetPath = path.join(publicScreenshotsDir, file);
      expect(fs.existsSync(assetPath)).toBe(true);
      expect(fs.statSync(assetPath).size).toBeGreaterThan(1000);
      expect(pageSource).toContain(`/screenshots/${file}`);

      const darkPath = path.join(darkScreenshotsDir, file);
      expect(fs.existsSync(darkPath)).toBe(true);
      expect(fs.statSync(darkPath).size).toBeGreaterThan(1000);
      expect(pageSource).toContain(`/screenshots/dark/${file}`);
    }
    expect(fs.existsSync(path.join(publicScreenshotsDir, "settings-shortcuts.png"))).toBe(
      false,
    );
  });

  it("links to the gallery and only embeds a few product shots on home", () => {
    // Craft home shows a handful of real app shots, then /screenshots/ for the rest.
    expect(homeSource).toContain('href="/screenshots/"');
    expect(homeSource).toContain("/screenshots/00-transcription.png");
    expect(homeSource).not.toContain("/screenshots/05-about-view.png");
    expect(homeSource).not.toContain("/screenshots/settings-recognition.png");
    expect(homeSource).not.toContain("/screenshots/settings-audio.png");
    expect(homeSource).not.toContain("/screenshots/settings-performance.png");
    expect(homeSource).not.toContain("/screenshots/settings-advanced.png");
  });

  it("exposes Screenshots in the shared site nav", () => {
    const navSource = fs.readFileSync(
      path.join(webRoot, "src/lib/site-nav.ts"),
      "utf-8",
    );
    expect(navSource).toContain('href: "/screenshots/"');
    expect(navSource).toContain('label: "Screenshots"');
    expect(shellSource).toContain("SiteChrome");
  });

  it("includes captioned settings and product sections", () => {
    expect(pageSource).toContain("Speech Model");
    expect(pageSource).toContain("Dictation");
    expect(pageSource).toContain("Audio");
    expect(pageSource).toContain("Performance");
    expect(pageSource).toContain("Application");
    expect(pageSource).toContain("Advanced");
    expect(pageSource).toContain("Dictation in action");
    expect(pageSource).toContain("About");
    expect(pageSource).toContain("update checker");
    expect(pageSource).not.toContain("Shortcuts & Hotkeys");
    expect(pageSource).not.toContain("About dialog");
    expect(pageSource).not.toContain("Settings overview");
  });
});
