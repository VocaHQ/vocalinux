import { GITHUB_REPO_URL, VOCAHQ_URL } from "@/lib/seo";

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

export const footerGroups: { title: string; links: NavLink[] }[] = [
  {
    title: "Product",
    links: [
      { href: "/#how-it-works", label: "How it works" },
      { href: "/#engines", label: "Engines" },
      { href: "/screenshots/", label: "Screenshots" },
      { href: "/changelog/", label: "Changelog" },
      { href: "/compare/", label: "Engine comparison" },
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
    title: "Desktop",
    links: [
      { href: "/wayland/", label: "Wayland" },
      { href: "/gpu-acceleration/", label: "GPU acceleration" },
      { href: "/desktop-reliability/", label: "Reliability" },
      { href: "/offline/", label: "Offline" },
      { href: "/remote-api/", label: "Remote API" },
    ],
  },
  {
    title: "Project",
    links: [
      { href: GITHUB_REPO_URL, label: "Source on GitHub" },
      { href: "/faq/", label: "FAQ" },
      { href: "/privacy/", label: "Privacy" },
      { href: "https://discord.gg/t6muquAJbm", label: "Discord" },
      { href: VOCAHQ_URL, label: "Part of the Voca family" },
    ],
  },
];
