# AGENTS.md — vocalinux.com (`web/`)

Guidelines for agents working on the marketing site only. For the Python desktop app, git worktrees, and PR rules, see the repo root [`AGENTS.md`](../AGENTS.md). Do not create branches, commits, or pull requests in the primary checkout.

## What this package is

Next.js (App Router) static marketing + SEO guides for Vocalinux. Source lives here; production deploys from `web/` (static export to `out/`).

## Product and design authority

Read these before changing marketing UI or copy:

| File | Holds |
|---|---|
| [`PRODUCT.md`](./PRODUCT.md) | Who the site is for, product truth, claims we can make |
| [`DESIGN.md`](./DESIGN.md) | Visual system: color, type, layout, components, don'ts |

Do not invent features, benchmarks, user counts, or privacy claims that contradict `PRODUCT.md`. Prefer screenshots and install commands over abstract feature theater.

## Commands

```bash
cd web
npm install
npm run dev          # local (prefer -H 0.0.0.0 -p 3456 when sharing)
npm run build        # static export
npm run lint
npm test
npm run typecheck
```

Viewport layout checks (needs a running server for the browser leg):

```bash
# with http://127.0.0.1:3456 up
BASE_URL=http://127.0.0.1:3456 npm test -- --testPathPatterns=viewport-layout
# or
npm run test:viewport
```

## Layout map

- Home: `src/app/page.tsx`
- Shared SEO shell: `src/components/seo-subpage-shell.tsx`
- Tokens / utilities: `src/styles/globals.css`, `tailwind.config.ts`
- Fonts: system display + body stacks in `src/styles/globals.css` (no remote webfonts)

## Maintaining this file

Update when website build, structure, or design authority paths change. Keep product claims and visual tokens in `PRODUCT.md` / `DESIGN.md`, not duplicated here.
