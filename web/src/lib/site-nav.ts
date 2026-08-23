import {
  DISCORD_URL,
  GITHUB_REPO_URL,
  VOCAHQ_URL,
  X_URL,
} from "@/lib/seo";

export type NavLink = {
  href: string;
  label: string;
};

export const homeNav: NavLink[] = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#engines", label: "Engines" },
  { href: "#privacy", label: "Privacy" },
  { href: "#install", label: "Install" },
  { href: "#faq", label: "Questions" },
];

export const pageNav: NavLink[] = [
  { href: "/", label: "Home" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/install/", label: "Install" },
  { href: "/screenshots/", label: "Screenshots" },
  { href: "/faq/", label: "Questions" },
];

export const mobileExtraNav: NavLink[] = [
  { href: "/compare/", label: "Compare engines" },
  { href: "/changelog/", label: "Changelog" },
  { href: "/troubleshooting/", label: "Troubleshooting" },
];

export const socialLinks: { href: string; label: string; icon: string }[] = [
  { href: X_URL, label: "X", icon: "/brand/social/x.svg" },
  { href: DISCORD_URL, label: "Discord", icon: "/brand/social/discord.svg" },
  { href: GITHUB_REPO_URL, label: "GitHub", icon: "/brand/social/github.svg" },
];

export const footerGroups: { title: string; links: NavLink[] }[] = [
  {
    title: "Product",
    links: [
      { href: "/#how-it-works", label: "How it works" },
      { href: "/screenshots/", label: "Screenshots" },
      { href: "/#engines", label: "Engines" },
      { href: "/compare/", label: "Compare engines" },
    ],
  },
  {
    title: "Install",
    links: [
      { href: "/#install", label: "Installation" },
      { href: "/install/", label: "Distro guides" },
      { href: "/install/ubuntu/", label: "Ubuntu" },
      { href: "/install/fedora/", label: "Fedora" },
      { href: "/install/arch/", label: "Arch" },
    ],
  },
  {
    title: "Guides",
    links: [
      { href: "/offline/", label: "Offline" },
      { href: "/wayland/", label: "Wayland" },
      { href: "/gpu-acceleration/", label: "GPU acceleration" },
      { href: "/desktop-reliability/", label: "Reliability" },
      { href: "/remote-api/", label: "Remote API" },
    ],
  },
  {
    title: "Project",
    links: [
      { href: "/faq/", label: "FAQ" },
      { href: "/privacy/", label: "Privacy" },
      { href: "/changelog/", label: "Changelog" },
      { href: GITHUB_REPO_URL, label: "Source" },
      { href: VOCAHQ_URL, label: "VocaHQ" },
    ],
  },
];
