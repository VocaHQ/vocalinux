import Link from "next/link";
import { type Metadata } from "next";
import { SiteChrome } from "@/components/site-chrome";
import { DidYouMean } from "@/components/not-found-extras";

export const metadata: Metadata = {
  title: "Page not found",
  description: "This page does not exist. Head back to the Vocalinux home page.",
  // Overrides the layout's "index, follow" so it agrees with Next's noindex.
  robots: { index: false, follow: true },
};

const quickLinks = [
  { href: "/install/", label: "Install guides" },
  { href: "/faq/", label: "FAQ" },
  { href: "/compare/", label: "Compare engines" },
  { href: "/troubleshooting/", label: "Troubleshooting" },
  { href: "/changelog/", label: "Changelog" },
];

// 404 is a fine number. These are all true; check them in a shell.
const stats = [
  {
    title: "chmod 404",
    body: "r-- --- r--. Owner and others can read, the group gets nothing, and nobody can write. Fitting for a page that isn't there.",
  },
  {
    title: "exit 404",
    body: "Exit statuses are 8 bits, so a shell reports $? = 148 (404 mod 256). Even the error code got truncated.",
  },
  {
    title: "0x194 · 0o624 · 0b110010100",
    body: "404 in hex, octal and binary. None of them is a valid URL on this site either.",
  },
];

export default function NotFound() {
  return (
    <SiteChrome variant="page">
      <div className="page-main">
        <div className="shell nf">
          <section className="nf-hero">
            <p className="nf-kicker">HTTP 404 · No such file or directory</p>
            <h1>
              This page is <em>not in your $PATH</em>.
            </h1>
            <p className="nf-lede">
              The link is broken, the page moved, or the URL picked up a typo
              on the way here. Vocalinux can type what you say, but it can&apos;t
              type a page that doesn&apos;t exist.
            </p>
          </section>

          <section className="nf-stats" aria-labelledby="nf-stats-title">
            <h2 id="nf-stats-title">Fun facts about 404</h2>
            <div className="nf-stat-grid">
              {stats.map((stat) => (
                <article className="nf-stat" key={stat.title}>
                  <h3>{stat.title}</h3>
                  <p>{stat.body}</p>
                </article>
              ))}
            </div>
          </section>

          <div className="nf-next">
            <DidYouMean />
            <div className="nf-actions">
              <Link className="btn btn-primary" href="/">
                Back to home
              </Link>
              <Link className="btn btn-secondary" href="/install/">
                Install Vocalinux
              </Link>
            </div>
            <nav className="nf-links" aria-label="Popular pages">
              {quickLinks.map((link) => (
                <Link key={link.href} href={link.href}>
                  {link.label}
                </Link>
              ))}
            </nav>
          </div>
        </div>
      </div>
    </SiteChrome>
  );
}
