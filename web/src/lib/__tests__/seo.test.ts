import { absoluteUrl } from "../seo";

describe("absoluteUrl", () => {
  it("returns the site root for /", () => {
    expect(absoluteUrl("/")).toBe("https://vocalinux.com/");
  });

  it("adds the trailing slash pages are served with", () => {
    expect(absoluteUrl("/install/debian")).toBe(
      "https://vocalinux.com/install/debian/",
    );
    expect(absoluteUrl("/faq/")).toBe("https://vocalinux.com/faq/");
  });

  it("leaves file URLs without a trailing slash", () => {
    expect(absoluteUrl("/vocalinux.png")).toBe(
      "https://vocalinux.com/vocalinux.png",
    );
    expect(absoluteUrl("/og-image.png")).toBe(
      "https://vocalinux.com/og-image.png",
    );
  });
});
