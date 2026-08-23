---
name: Vocalinux website
description: Linux voice dictation marketing site in the Voca family workbench language
colors:
  paper: "#f4f1e8"
  paper-deep: "#ebe5d8"
  paper-bright: "#fffdf7"
  ink: "#14231c"
  muted-copy: "#58625c"
  faint: "#5f6861"
  line: "#c9c8bd"
  brand: "#0f6b57"
  brand-dark: "#0b493d"
  brand-soft: "#cfe9dc"
  brand-softer: "#e5f2eb"
  dark-ink: "#0b1a15"
  sun: "#e9b949"
  red: "#de6a57"
  terminal: "#0b1a15"
  terminal-fg: "#cfe9dc"
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

**Creative north star: the Linux desk in the Voca family**

Vocalinux.com is a Voca product site. It should feel related to VocaHQ, VocaMac, VocaPhone, and VocaGateway before anyone reads the logo: warm paper, deep green ink, one teal accent, editorial type, flat surfaces, and real product proof.

The Linux-specific job is to show local desktop dictation with distribution and display-server truth. Pair a GTK-style window (not macOS traffic lights) with a terminal. Explain the user outcome before the install command.

Child pages share the same shell, tokens, and paper canvas. Paper is the only
marketing theme. There is no site-wide dark mode. The screenshots gallery is
the exception: a page-local Light/Dark flip shows the captured GTK shots in
both appearances, defaulting to `prefers-color-scheme` until the visitor
overrides it for that tab.

## Colors

Warm paper with one product teal. No second chromatic brand color.

### Surfaces
- **Paper** `#f4f1e8`: page canvas
- **Deep paper** `#ebe5d8`: recessed bands (install, engines)
- **Bright paper** `#fffdf7`: windows and cards
- **Dark ink** `#0b1a15`: panel bar, terminal, optional dark band

### Ink
- **Ink** `#14231c`: headings and strong borders
- **Muted copy** `#58625c`: body
- **Faint** `#5f6861`: metadata
- **Line** `#c9c8bd`: quiet borders
- **Line dark** `#9ea59f`: window outlines

### Accent
- **Brand teal** `#0f6b57`: primary buttons, links, live marks
- **Dark teal** `#0b493d`: hover / pressed
- **Mint** `#cfe9dc` / **mint soft** `#e5f2eb`: tags and chips

### Annotations only
- **Sun** `#e9b949`: focus rings
- **Red** `#de6a57`: recording dot, never as a brand fill

### Named rules
**The family paper rule.** Backgrounds stay warm paper, with dark ink only for the tray bar, terminal, and ribbon. Not zinc white, not a second site-wide dark theme, not purple mesh.

**The one signal rule.** Teal is the only chromatic accent on marketing pages. Yellow and red are physical details (focus, recording), not competing brands.

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
- **Body:** 16–18px, line-height ~1.65, max ~65ch
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
- Primary: brand teal, paper-bright text, 44px min height
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
