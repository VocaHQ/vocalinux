import {
  DISCORD_URL,
  EMAIL_URL,
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
  { href: EMAIL_URL, label: "Email hello@vocahq.com", icon: "/brand/social/mail.svg" },
];

export const footerGroups: { title: string; links: NavLink[] }[] = [
  {
    title: "Product",
    links: [
      { href: "/#how-it-works", label: "How it works" },
      { href: "/screenshots/", label: "Screenshots" },
      { href: "/#engines", label: "Engines" },
      { href: "/compare/", label: "Compare engines" },
      { href: "/parakeet/", label: "Parakeet engine" },
      { href: "/faster-whisper/", label: "Faster Whisper" },
      { href: "/alternatives/", label: "Alternatives" },
      { href: "/vs-nerd-dictation/", label: "vs Nerd Dictation" },
    ],
  },
  {
    title: "Install",
    links: [
      { href: "/install/", label: "Distro guides" },
      { href: "/install/ubuntu/", label: "Ubuntu" },
      { href: "/install/debian/", label: "Debian" },
      { href: "/install/fedora/", label: "Fedora" },
      { href: "/install/arch/", label: "Arch" },
      { href: "/install/linux-mint/", label: "Linux Mint" },
      { href: "/install/pop-os/", label: "Pop!_OS" },
      { href: "/install/opensuse/", label: "openSUSE" },
      { href: "/install/nixos/", label: "NixOS" },
      { href: "/flatpak/", label: "Flatpak" },
    ],
  },
  {
    title: "Guides",
    links: [
      { href: "/offline/", label: "Offline" },
      { href: "/wayland/", label: "Wayland" },
      { href: "/hyprland-sway/", label: "Hyprland and Sway" },
      { href: "/pipewire/", label: "PipeWire" },
      { href: "/gpu-acceleration/", label: "GPU acceleration" },
      { href: "/whisper-model-guide/", label: "Whisper models" },
      { href: "/desktop-reliability/", label: "Reliability" },
      { href: "/remote-api/", label: "Remote API" },
      { href: "/voice-typing-vscode/", label: "VS Code" },
      { href: "/writers/", label: "For writers" },
    ],
  },
  {
    title: "Features",
    links: [
      { href: "/dictation-pad/", label: "Dictation Pad" },
      { href: "/transcribe-audio-files/", label: "Transcribe audio files" },
      { href: "/custom-dictionary/", label: "Custom dictionary" },
      { href: "/multilingual-dictation/", label: "Multilingual dictation" },
      { href: "/global-shortcuts/", label: "Global shortcuts" },
      { href: "/shortcuts/", label: "Voice commands" },
      { href: "/local-gateway/", label: "Local gateway" },
    ],
  },
  {
    title: "Project",
    links: [
      { href: "/faq/", label: "FAQ" },
      { href: "/troubleshooting/", label: "Troubleshooting" },
      { href: "/privacy/", label: "Privacy" },
      { href: "/changelog/", label: "Changelog" },
      { href: GITHUB_REPO_URL, label: "Source" },
      { href: VOCAHQ_URL, label: "VocaHQ" },
    ],
  },
];
