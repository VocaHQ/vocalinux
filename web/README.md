# Vocalinux Website

This is the official website for Vocalinux, a voice-to-text application for Linux systems. The website is built with Next.js and can be deployed as a static site to GitHub Pages.

## 🚀 Quick Start

### Development
```bash
npm install
npm run dev
```

### Building for Production
```bash
npm install
npm run build
```

The static files will be generated in the `out/` directory.

## 📦 Deployment to GitHub Pages

### Automatic Deployment (Recommended)

1. **Push your changes** to the `main` or `master` branch
2. **GitHub Actions will automatically build and deploy** your site to the `gh-pages` branch
3. **Custom Domain**: The site is configured for `vocalinux.com`
4. **The site will be available** at https://vocalinux.com

### Manual Deployment

If you prefer to deploy manually:

1. **Build the static site:**
   ```bash
   cd web
   npm install
   npm run deploy
   ```

2. **The build includes:**
   - Static HTML, CSS, and JavaScript files in `out/`
   - `.nojekyll` file for GitHub Pages compatibility
   - `CNAME` file pointing to `vocalinux.com`

### Local Testing

To test the built site locally:
```bash
cd web/out
python3 -m http.server 3000
```

Then visit `http://localhost:3000` in your browser.

## 🛠️ Build Scripts

- `npm run dev` - Start development server
- `npm run build` - Build static site for production
- `npm run deploy` - Build and prepare for GitHub Pages (adds .nojekyll and CNAME)
- `npm run lint` - Run ESLint
- `npm run typecheck` - Run TypeScript type checking

## 📁 Project Structure

```
web/
├── src/
│   ├── app/
│   │   ├── layout.tsx          # Root layout
│   │   └── page.tsx            # Homepage
│   ├── components/
│   │   ├── site-chrome.tsx
│   │   └── ui/                 # Reusable UI components
│   ├── hooks/
│   └── lib/
├── public/                     # Static assets
├── out/                        # Generated static files (after build)
└── package.json
```

## 🎨 Features

- **Responsive Design** - Works on desktop and mobile
- **Family workbench UI** - Warm paper, system type, same language as VocaHQ
- **Modern UI** - Built with Tailwind CSS
- **SEO Optimized** - Proper meta tags and structure
- **Fast Loading** - Optimized static generation

## 🔧 Configuration

### Custom Domain

If you want to use a custom domain:

1. Update the `deploy` script in `package.json` to include your domain:
   ```json
   "deploy": "next build && touch out/.nojekyll && echo 'yourdomain.com' > out/CNAME"
   ```

2. Configure your domain's DNS to point to GitHub Pages

### Base Path

If deploying to a subdirectory, update `next.config.js`:
```javascript
const config = {
  basePath: '/your-subdirectory',
  // ... other config
}
```

## 🐛 Troubleshooting

### Build Issues

- **"Module not found"**: Run `npm install` to ensure all dependencies are installed
- **TypeScript errors**: Run `npm run typecheck` to see detailed type errors
- **ESLint errors**: Run `npm run lint:fix` to automatically fix common issues

### Deployment Issues

- **404 on GitHub Pages**: Ensure `.nojekyll` file exists in the `out/` directory
- **Assets not loading**: Check that `basePath` is correctly configured in `next.config.js`
- **Blank page**: Check browser console for JavaScript errors

## 📝 License

This project is licensed under the same license as the main Vocalinux project.
