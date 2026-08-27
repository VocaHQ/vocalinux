/**
 * Rasterize the circular mark into favicons and render the family OG image.
 * Usage: node scripts/render-social-assets.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { chromium } from "playwright-core";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pub = join(root, "public");
const mark = join(pub, "brand/vocalinux-mark-circle.svg");
const chrome =
  process.env.CHROME_PATH ||
  ["/usr/bin/chromium-browser", "/usr/bin/chromium"].find(Boolean);

function convertPng(size, dest, { paper } = {}) {
  const args = ["-background", paper ? "#f4f1e8" : "none", "-resize", `${size}x${size}`, mark];
  if (paper) {
    args.push("-gravity", "center", "-extent", `${size}x${size}`);
  }
  args.push("-depth", "8", `png32:${dest}`);
  execFileSync("convert", args);
}

function toWebp(src, dest) {
  execFileSync("convert", [src, dest]);
}

const skipIcons = process.env.OG_ONLY === "1";

const sizes = [
  [16, join(pub, "favicon-16x16.png")],
  [32, join(pub, "favicon-32x32.png")],
  [32, join(pub, "vocalinux-32x32.png")],
  [64, join(pub, "vocalinux-64x64.png")],
  [96, join(pub, "favicon-96x96.png")],
  [96, join(pub, "vocalinux-96x96.png")],
  [192, join(pub, "vocalinux-192x192.png")],
  [192, join(pub, "icon-192x192.png")],
  [512, join(pub, "vocalinux-512x512.png")],
  [512, join(pub, "icon-512x512.png")],
  [512, join(pub, "vocalinux.png")],
];

if (!skipIcons) {
  for (const [size, dest] of sizes) {
    convertPng(size, dest);
    if (dest.endsWith(".png") && !dest.includes("favicon-")) {
      const webp = dest.replace(/\.png$/i, ".webp");
      if (
        dest.includes("vocalinux-") ||
        dest.endsWith("/vocalinux.png")
      ) {
        toWebp(dest, webp);
      }
    }
  }

  convertPng(180, join(pub, "apple-touch-icon.png"), { paper: true });
  execFileSync("convert", [
    join(pub, "favicon-16x16.png"),
    join(pub, "favicon-32x32.png"),
    join(pub, "favicon.ico"),
  ]);
}

const markSvg = readFileSync(mark, "utf8");
const markData = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markSvg)}`;
const tuxData = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
  readFileSync(join(pub, "brand/tux.svg"), "utf8"),
)}`;
const dotsData = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
  readFileSync(join(pub, "brand/paper-dots.svg"), "utf8"),
)}`;

const ogHtml = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<style>
  html, body { margin: 0; width: 1200px; height: 630px; overflow: hidden; }
  body {
    color: #14231c;
    background-color: #f4f1e8;
    background-image: url("${dotsData}");
    font-family: "Avenir Next", "Helvetica Neue", ui-sans-serif, system-ui, "Segoe UI", Arial, sans-serif;
  }
  .frame { display: flex; height: 630px; padding: 48px 40px 40px 64px; box-sizing: border-box; gap: 28px; }
  .copy { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; }
  .brand { display: flex; align-items: center; gap: 14px; font-size: 28px; font-weight: 600; letter-spacing: -0.03em; }
  .brand img { width: 56px; height: 56px; border-radius: 50%; }
  h1 { margin: 28px 0 0; font-size: 72px; font-weight: 780; letter-spacing: -0.075em; line-height: 0.92; }
  h1 em { font-style: normal; color: #0f6b57; }
  .lede { margin: 22px 0 0; max-width: 22em; color: #58625c; font-size: 22px; line-height: 1.45; }
  .proof { display: flex; flex-wrap: wrap; gap: 10px 18px; margin-top: 28px; padding-top: 22px; border-top: 1px solid #c9c8bd; color: #5f6861; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 15px; }
  .proof span + span { padding-left: 18px; border-left: 1px solid #c9c8bd; }
  .url { margin-top: 26px; color: #5f6861; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 14px; }
  .right { position: relative; width: 520px; flex: none; align-self: stretch; }
  .workbench { width: 340px; margin-top: 36px; }
  .tux { position: absolute; right: 0; bottom: 0; height: 430px; width: auto; }
  .panel { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; color: #fffdf7; background: #0b1a15; border-radius: 10px; font-size: 14px; }
  .rec { width: 8px; height: 8px; margin-right: 6px; border-radius: 50%; background: #de6a57; display: inline-block; }
  .window { margin-top: 10px; background: #fffdf7; border: 1px solid #9ea59f; border-radius: 12px; overflow: hidden; }
  .titlebar { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: #ebe5d8; border-bottom: 1px solid #c9c8bd; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; color: #5f6861; }
  .dots { display: flex; gap: 5px; }
  .dots i { width: 10px; height: 10px; border-radius: 50%; border: 1px solid #5c7d71; background: #fffdf7; display: block; }
  .dots i.close { background: #cfe9dc; }
  .body { padding: 18px 18px 16px; }
  .ready { font-size: 18px; font-weight: 650; }
  .hint { margin-top: 4px; color: #58625c; font-size: 13px; }
  .line { margin-top: 16px; padding: 12px 14px; background: #f4f1e8; border-radius: 8px; font-size: 16px; }
  .caret { display: inline-block; width: 2px; height: 1em; margin-left: 3px; background: #0f6b57; vertical-align: -2px; }
</style>
</head>
<body>
  <div class="frame">
    <div class="copy">
      <div class="brand">
        <img src="${markData}" alt="" />
        Vocalinux
      </div>
      <h1>Dictate locally.<br><em>In any app.</em></h1>
      <p class="lede">Hold Right Alt. Text lands in the focused window. Local engines by default.</p>
      <div class="proof">
        <span>X11 and Wayland</span>
        <span>No telemetry</span>
        <span>AGPL-3.0</span>
      </div>
      <p class="url">vocalinux.com</p>
    </div>
    <div class="right">
      <div class="workbench">
        <div class="panel"><span>Vocalinux</span><span><i class="rec"></i>listening</span></div>
        <div class="window">
          <div class="titlebar"><span>notes.txt</span><span class="dots" aria-hidden="true"><i></i><i></i><i class="close"></i></span></div>
          <div class="body">
            <div class="ready">Ready to dictate</div>
            <div class="hint">Hold Right Alt to record</div>
            <div class="line">the words go where you are already working<i class="caret"></i></div>
          </div>
        </div>
      </div>
      <img class="tux" src="${tuxData}" alt="Tux, the Linux mascot" />
    </div>
  </div>
</body>
</html>
`;

const browser = await chromium.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});
const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
await page.setContent(ogHtml, { waitUntil: "load" });
await page.screenshot({ path: join(pub, "og-image.png"), type: "png" });
await browser.close();

execFileSync("convert", [join(pub, "og-image.png"), join(pub, "og-image.webp")]);
console.log("rendered circular favicons and family OG image");
