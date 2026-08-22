/**
 * @jest-environment node
 *
 * Structural + real-browser layout checks for the marketing home page.
 *
 * 1. Structural: shipped CSS/markup include overflow guards (break-all, min-w-0).
 * 2. Browser: when BASE_URL is set (or local :3456 is up), playwright-core + system
 *    Chrome measures scrollWidth vs clientWidth at three viewports.
 *
 * Run browser leg:
 *   BASE_URL=http://127.0.0.1:3456 npm test -- --testPathPatterns=viewport-layout
 */
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const pageTsx = fs.readFileSync(path.join(root, "src/app/page.tsx"), "utf8");
const terminalTsx = fs.readFileSync(
  path.join(root, "src/components/terminal-block.tsx"),
  "utf8",
);
const chromeTsx = fs.readFileSync(
  path.join(root, "src/components/site-chrome.tsx"),
  "utf8",
);
const globalsCss = fs.readFileSync(
  path.join(root, "src/styles/globals.css"),
  "utf8",
);
const homeSource = `${pageTsx}\n${terminalTsx}\n${chromeTsx}`;

const CHROME =
  process.env.CHROME_PATH ||
  ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"].find(
    (p) => fs.existsSync(p),
  );

async function resolveBaseUrl(): Promise<string | null> {
  if (process.env.BASE_URL) return process.env.BASE_URL.replace(/\/$/, "");
  try {
    const res = await fetch("http://127.0.0.1:3456/", { signal: AbortSignal.timeout(2000) });
    if (res.ok) return "http://127.0.0.1:3456";
  } catch {
    /* offline */
  }
  return null;
}

describe("marketing home layout guards (shipped source)", () => {
  it("terminal and main constrain long monospace without page-wide overflow", () => {
    expect(globalsCss).toMatch(/overflow-x:\s*clip/);
    expect(globalsCss).toMatch(/\.terminal-panel pre/);
    expect(globalsCss).toMatch(/overflow-wrap:\s*anywhere|break-all|word-break/);
    expect(homeSource).toMatch(/break-all/);
    expect(homeSource).toMatch(/min-w-0/);
    expect(homeSource).toMatch(/overflow-x-clip|overflow-x-auto/);
  });

  it("hero uses solid display type (no gradient text slop)", () => {
    expect(pageTsx).not.toMatch(/bg-clip-text/);
    expect(pageTsx).not.toMatch(/bg-gradient-to-r from-primary via-teal/);
    expect(pageTsx).toMatch(/font-display/);
    expect(pageTsx).toMatch(/TerminalBlock|terminal-panel/);
  });

  it("uses the Voca family paper workbench tokens", () => {
    expect(globalsCss).toMatch(/--paper:\s*#f4f1e8/);
    expect(globalsCss).toMatch(/--brand:\s*#0f6b57/);
    expect(globalsCss).not.toMatch(/linear-gradient|radial-gradient|conic-gradient/);
    expect(pageTsx).not.toMatch(/linear-gradient|radial-gradient|conic-gradient/);
  });
});

describe("marketing home three-viewport overflow (live browser)", () => {
  const viewports = [
    { name: "desktop", width: 1280, height: 800 },
    { name: "tablet", width: 768, height: 1024 },
    { name: "mobile", width: 390, height: 844 },
  ];

  it("has no horizontal overflow and keeps hero + install terminal in bounds", async () => {
    const baseUrl = await resolveBaseUrl();
    if (!baseUrl) {
      console.warn("Skipping live browser leg: no BASE_URL and :3456 not up");
      return;
    }
    if (!CHROME) {
      console.warn("Skipping live browser leg: no Chrome binary");
      return;
    }

    const { chromium } = await import("playwright-core");
    const browser = await chromium.launch({
      executablePath: CHROME,
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    });

    try {
      for (const vp of viewports) {
        const context = await browser.newContext({
          viewport: { width: vp.width, height: vp.height },
        });
        const page = await context.newPage();
        await page.goto(`${baseUrl}/`, { waitUntil: "networkidle", timeout: 60000 });
        await page.waitForSelector("h1");

        const metrics = await page.evaluate(() => {
          const de = document.documentElement;
          const hero = document.querySelector("h1");
          const terminal = document.querySelector(".terminal-panel");
          const heroRect = hero?.getBoundingClientRect();
          const termRect = terminal?.getBoundingClientRect();
          const inBounds = (r?: DOMRect) =>
            !!r &&
            r.width > 0 &&
            r.height > 0 &&
            r.left >= -1 &&
            r.right <= de.clientWidth + 1;
          return {
            overflowX: de.scrollWidth > de.clientWidth + 1,
            scrollWidth: de.scrollWidth,
            clientWidth: de.clientWidth,
            heroInBounds: inBounds(heroRect),
            terminalInBounds: inBounds(termRect),
            hasGradientText: !!document.querySelector('[class*="bg-clip-text"]'),
            hasVocalinux: document.body.innerText.includes("Vocalinux"),
          };
        });

        expect({
          viewport: vp.name,
          ...metrics,
        }).toEqual(
          expect.objectContaining({
            overflowX: false,
            heroInBounds: true,
            terminalInBounds: true,
            hasGradientText: false,
            hasVocalinux: true,
          }),
        );

        if (vp.width < 768) {
          await page.getByRole("button", { name: /toggle menu/i }).click();
          const howVisible = await page
            .locator("header")
            .getByRole("link", { name: "How it works" })
            .isVisible();
          expect(howVisible).toBe(true);
        }

        await context.close();
      }
    } finally {
      await browser.close();
    }
  }, 120000);
});
