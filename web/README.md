# Vocalinux website

Marketing site for [vocalinux.com](https://vocalinux.com), built with Next.js and deployed as a static export (GitHub Pages).

Product claims and design constraints: [PRODUCT.md](PRODUCT.md), [DESIGN.md](DESIGN.md). Agent notes: [AGENTS.md](AGENTS.md).

## Development

```bash
npm install
npm run dev
```

## Production build

```bash
npm install
npm run build
```

Static output is written to `out/`.

### Local preview of the build

```bash
cd out
python3 -m http.server 3000
```

Open `http://localhost:3000`.

## Scripts

| Script | Purpose |
|--------|---------|
| `npm run dev` | Dev server |
| `npm run build` | Production static export |
| `npm run deploy` | Build and prepare GitHub Pages (`.nojekyll`, `CNAME`) |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript |

## Deployment

Push to `main` triggers the site workflow. Production host: **vocalinux.com**.

Manual path:

```bash
cd web
npm install
npm run deploy
```

That produces `out/` with `.nojekyll` and a `CNAME` for vocalinux.com.

## Layout

```
web/
├── src/
│   ├── app/            # Next.js app routes
│   ├── components/
│   │   ├── site-chrome.tsx
│   │   └── ui/         # Reusable UI components
│   ├── hooks/
│   └── lib/
├── public/             # Static assets and screenshots
├── out/                # Build output (generated)
└── package.json
```

## Configuration notes

- Custom domain: `deploy` script writes `out/CNAME`
- Subdirectory deploy: set `basePath` in `next.config.js` if needed
- Family workbench UI: warm paper, system type, same language as VocaHQ ([DESIGN.md](DESIGN.md))

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Module not found | `npm install` |
| Type errors | `npm run typecheck` |
| Lint errors | `npm run lint` |
| 404 on GitHub Pages | Ensure `out/.nojekyll` exists |
| Assets 404 | Confirm `basePath` matches deploy path |

## License

Same as the main Vocalinux project ([AGPL-3.0](../LICENSE)).
