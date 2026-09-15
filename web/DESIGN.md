---
name: Vocalinux website
description: Linux voice dictation marketing site on iron-white with emerald accent
colors:
  paper: "#ffffff"
  paper-deep: "#f4f4f5"
  paper-bright: "#ffffff"
  ink: "#09090b"
  muted-copy: "#52525b"
  faint: "#71717a"
  line: "#e4e4e7"
  brand: "#1a7f4e"
  brand-dark: "#14663e"
  brand-soft: "#d1fae5"
  brand-softer: "#ecfdf3"
  dark-ink: "#0a0a0c"
  sun: "#e9b949"
  red: "#c45c5c"
  terminal: "#0a0a0c"
  terminal-fg: "#6ee7a8"
typography:
  display: '"Avenir Next", "Helvetica Neue", ui-sans-serif, system-ui, "Segoe UI", Arial, sans-serif'
  body: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  mono: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace'
rounded:
  sm: "0.45rem"
  md: "1rem"
  lg: "1.4rem"
spacing:
  shell: "min(1180px, calc(100% - 2rem))"
  section-y: "5.5rem"
---

# Design system: vocalinux.com

## Overview

**Creative north star: the Linux desk on iron-white**

Vocalinux.com is a Voca product site. It should feel related to VocaHQ, VocaMac, VocaPhone, and VocaGateway before anyone reads the logo: iron-white canvas, near-black iron ink, one emerald accent (`#1a7f4e`), editorial type, flat surfaces, and real product proof.

The Linux-specific job is to show local desktop dictation with distribution and display-server truth. Pair a GTK-style window (not macOS traffic lights) with a terminal. Explain the user outcome before the install command.

Child pages share the same shell, tokens, and paper canvas. Paper is the only
marketing theme. There is no site-wide dark mode. The screenshots gallery is
the exception: a page-local Light/Dark flip shows the captured GTK shots in
both appearances, defaulting to `prefers-color-scheme` until the visitor
overrides it for that tab.

## Colors

Iron-white with one product emerald (`#1a7f4e`). No second chromatic brand color. Never warm cream or beige as the default canvas.

### Surfaces
- **Paper / iron-white** `#ffffff`: page canvas
- **Deep paper** `#f4f4f5`: recessed bands (install, engines)
- **Bright paper** `#ffffff`: windows and cards
- **Dark ink** `#0a0a0c`: panel bar, terminal, optional dark band

### Ink
- **Ink** `#09090b`: headings and strong borders
- **Muted copy** `#52525b`: body
- **Faint** `#71717a`: metadata
- **Line** `#e4e4e7`: quiet borders
- **Line dark** `#d4d4d8`: window outlines

### Accent
- **Brand / emerald** `#1a7f4e`: primary buttons, links, live marks
- **Brand dark** `#14663e`: hover / pressed
- **Accent foreground** `#14532d`: text on mint chips
- **Mint** `#d1fae5` / **mint soft** `#ecfdf3`: tags and chips
- **Terminal fg** `#6ee7a8`: mint-on-iron command text

### Annotations only
- **Sun** `#e9b949`: focus rings
- **Red** `#c45c5c`: recording dot, never as a brand fill

### Named rules
**The iron surface rule.** Backgrounds stay iron-white (`#ffffff`) and raised iron (`#f4f4f5`). Never warm cream or beige as the default canvas. Dark ink only for the tray bar, terminal, and ribbon. Not a second site-wide dark theme, not purple mesh.

**The one signal rule.** Emerald `#1a7f4e` is the only chromatic accent on marketing pages. Yellow and red are physical details (focus, recording), not competing brands.

**The no-gradient rule.** Solid fills only. No linear, radial, or conic gradients.

## Typography

System-first, same stacks as VocaHQ / VocaMac.

- **Display:** Avenir Next / Helvetica Neue / Segoe UI / Arial
- **Body:** system UI sans
- **Mono:** system UI monospace for commands, tags, and metadata

No remote webfonts. No Geist, Inter, or Bricolage as the page face.

### Hierarchy
- **Hero display:** clamp ~3.7–7.4rem, weight ~780, tracking -0.075em, line-height ~0.92
- **Section title:** clamp ~2.2–4.7rem, tracking -0.065em
- **Body:** 16–18px, line-height ~1.65. Reflow with the shell; do not pretty-wrap or cap titles at 20ch
- **Mono tags:** ~0.7rem, used sparingly

Accent words in a headline use the same family, `font-style: normal`, brand color. Do not mix a second family into a heading.

## Layout

- Shell: `min(1180px, calc(100% - 2rem))`
- Sticky paper header, ~70px, one line of nav on desktop
- Home first viewport: split offer + Linux workbench when wide; stacked on small screens
- Section padding ~5.5–9rem desktop, ~4–6rem mobile
- Alternate paper / deep paper for rhythm
- Child pages: breadcrumbs + content in the same shell

## Elevation and shapes

Flat fills, 1px borders, paper-window shadows. Small rotations only on decorative notes, never on long copy or controls.

- Controls: 0.45rem radius
- Windows: ~10–14px radius
- Pills only for tiny tags (engine badge, section tag)

## Components

### Buttons
- Primary: brand emerald, paper-bright text, 44px min height
- Homepage / closing CTA: "Install Vocalinux", jumps to `#install`
- Secondary: transparent with a 3:1 control outline
- Hover: 2px lift, no bounce scale as the only affordance
- Focus: 3px sun outline, 3px offset

### Linux window
- GTK-style headerbar: title, then window controls on the **right**
- Grey control circles, not red/yellow/green traffic lights
- Bright paper body, dark ink panel bar above (tray analogue)

### Terminal
- Dark ink surface, mint command text, copy in the chrome
- GTK headerbar: copy on the left, title centered, grey window controls on the **right**
- Prompt is `user@linux:~$` with colored user, host, and path, not a Mac `$`
- Long URLs wrap (`break-all` / `overflow-wrap`) so mobile never overflows

### Navigation
- Sticky paper bar, mark + name, 3–5 text links, GitHub stars on desktop
- Mobile menu keeps Install Vocalinux as the conversion action
- Real mobile disclosure with `aria-expanded`
- Resource-rich footer, not a second mega-menu in the header

### Screenshot gallery
- Paper chrome stays paper; do not put `html.dark` on this page
- Light/Dark is a sliding switch over stacked light and dark PNG pairs
- Default from the browser color scheme; `sessionStorage` holds a tab override

## Do's and don'ts

### Do
- Lead with the dictation outcome, then the install command
- Use real screenshots and a faithful Linux window, not a fake SaaS dashboard
- Keep product claims accurate (offline local engines; remote only when configured)
- Honor `prefers-reduced-motion`

### Don't
- CSS gradients, gradient text, mesh/orbs, or glass panels
- macOS traffic-light chrome on Linux surfaces
- Tracked uppercase eyebrows on every section
- Invent metrics, testimonials, or "AI-powered" claims
- Recolor the Vocalinux mark
