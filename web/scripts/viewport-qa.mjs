#!/usr/bin/env node
/**
 * Viewport QA for the Vocalinux marketing home page.
 * Uses system Google Chrome via playwright-core (no browser download).
 *
 * Usage:
 *   node scripts/viewport-qa.mjs [baseUrl] [outDir] [passLabel]
 *
 * Exit 0 only when every configured viewport has no horizontal overflow
 * and the primary hero + install terminal are present and in-bounds.
 */
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const baseUrl = process.argv[2] || "http://127.0.0.1:3456";
const outDir = process.argv[3] || path.join(process.cwd(), "viewport-qa-out");
const passLabel = process.argv[4] || "pass";

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
];

const CHROME =
  process.env.CHROME_PATH ||
  ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"].find(
    (p) => fs.existsSync(p),
  );

if (!CHROME) {
  console.error("No Chrome binary found. Set CHROME_PATH.");
  process.exit(2);
}

fs.mkdirSync(outDir, { recursive: true });

const results = [];

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});

try {
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (err) => pageErrors.push(String(err)));

    await page.goto(baseUrl + "/", { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForSelector("h1", { timeout: 15000 });

    const metrics = await page.evaluate(() => {
      const de = document.documentElement;
      const hero = document.querySelector("h1");
      const terminal = document.querySelector(".terminal-panel");
      const install = document.querySelector("#install");
      const nav = document.querySelector("header nav");
      const overflowX = de.scrollWidth > de.clientWidth + 1;
      const bodyText = document.body.innerText;
      const heroRect = hero ? hero.getBoundingClientRect() : null;
      const terminalRect = terminal ? terminal.getBoundingClientRect() : null;
      const inBounds = (r) =>
        !!r && r.width > 0 && r.height > 0 && r.left >= -1 && r.right <= de.clientWidth + 1;

      return {
        scrollWidth: de.scrollWidth,
        clientWidth: de.clientWidth,
        overflowX,
        hasVocalinux: bodyText.includes("Vocalinux"),
        hasInstallCta: !!document.querySelector('a[href="#install"]'),
        hasGradientText: !!document.querySelector('[class*="bg-clip-text"]'),
        h1: hero ? hero.innerText.trim() : null,
        heroInBounds: inBounds(heroRect),
        terminalInBounds: terminal ? inBounds(terminalRect) : false,
        installPresent: !!install,
        navPresent: !!nav,
        heroWidth: heroRect ? heroRect.width : null,
        terminalWidth: terminalRect ? terminalRect.width : null,
      };
    });

    const shotName =
      passLabel === "pass1" || passLabel === "1"
        ? `${vp.name}.png`
        : passLabel === "pass2" || passLabel === "2" || passLabel === "after"
          ? `${vp.name}-after.png`
          : `${vp.name}-${passLabel}.png`;

    await page.screenshot({
      path: path.join(outDir, shotName),
      fullPage: false,
    });

    // Install section shot for mobile proof
    if (vp.name === "mobile") {
      await page.locator("#install").scrollIntoViewIfNeeded();
      await page.waitForTimeout(200);
      await page.screenshot({
        path: path.join(outDir, shotName.replace(".png", "-install.png")),
        fullPage: false,
      });
    }

    // Mobile menu path check (header only)
    let mobileMenuOk = true;
    if (vp.width < 768) {
      const toggle = page.getByRole("button", { name: /toggle menu/i });
      if (await toggle.count()) {
        await toggle.click();
        await page.waitForTimeout(150);
        mobileMenuOk = await page
          .locator("header")
          .getByRole("link", { name: "How it works" })
          .isVisible();
        await toggle.click();
      } else {
        mobileMenuOk = false;
      }
    }

    const ok =
      !metrics.overflowX &&
      metrics.hasVocalinux &&
      metrics.hasInstallCta &&
      !metrics.hasGradientText &&
      metrics.heroInBounds &&
      metrics.terminalInBounds &&
      metrics.navPresent &&
      mobileMenuOk &&
      pageErrors.length === 0;

    results.push({
      viewport: vp,
      ok,
      metrics,
      mobileMenuOk,
      pageErrors,
      screenshot: shotName,
    });

    await context.close();
  }
} finally {
  await browser.close();
}

const summary = {
  baseUrl,
  chrome: CHROME,
  passLabel,
  allOk: results.every((r) => r.ok),
  results,
};

const jsonName =
  passLabel === "pass1" || passLabel === "1"
    ? "viewport-pass1.json"
    : passLabel === "pass2" || passLabel === "2" || passLabel === "after"
      ? "viewport-pass2.json"
      : `viewport-${passLabel}.json`;

fs.writeFileSync(path.join(outDir, jsonName), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));

if (!summary.allOk) {
  process.exit(1);
}
