import { PHASE_PRODUCTION_BUILD } from 'next/constants.js';

// @ts-ignore
/** @type {import("next").NextConfig} */
const config = {
	output: 'export',
	trailingSlash: true,
	// Configuration for custom domain deployment
	distDir: 'out',

	// Cache/security headers live in public/_headers (copied into the static
	// export). next.config headers() is ignored with output: 'export' and only
	// produces build warnings.
	images: {
		unoptimized: true,
		formats: ['image/avif', 'image/webp'],
		remotePatterns: [
			{
				protocol: 'https',
				hostname: '*',
				pathname: '**',
			},
		],
	},
	eslint: {
		ignoreDuringBuilds: true,
	},
	typescript: {
		ignoreBuildErrors: true,
	},
	// Disable source maps in production to reduce bundle size
	productionBrowserSourceMaps: false,
	// Use modern JavaScript for better performance and smaller bundle sizes
	experimental: {
		optimizePackageImports: ['lucide-react', 'framer-motion'],
	},
	webpack: (config, { isServer, dev }) => {
		// Only use source maps in development
		if (!dev) {
			config.devtool = false;
		}
		// Enhanced node polyfills for postgres and other modules
		if (!isServer) {
			config.resolve.fallback = {
				...config.resolve.fallback,
				// File system - never needed in browser
				fs: false,
				net: false,
				tls: false,
				crypto: false,
				stream: false,
				'perf_hooks': false,

				// Definitely not needed in browser
				child_process: false,
				dns: false,
			};

			// Configure swc to output modern JavaScript (ES2022) instead of ES5
			// This eliminates unnecessary polyfills and reduces bundle size
			if (config.optimization && config.optimization.minimizer) {
				config.optimization.minimizer.forEach((minimizer) => {
					if (minimizer.constructor.name === 'TerserPlugin') {
						minimizer.options.compress = {
							...minimizer.options.compress,
							pure_funcs: ['console.log', 'console.debug'],
						};
					}
				});
			}
		}
		return config;
	},
};

// The header star count is fetched once per production build and inlined, so
// visitors never call api.github.com (Lighthouse flagged it as third-party
// code on every page). Any failure falls back to the plain "GitHub" label.
async function fetchGitHubStars() {
	try {
		const res = await fetch('https://api.github.com/repos/VocaHQ/vocalinux', {
			headers: process.env.GITHUB_TOKEN
				? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` }
				: {},
			signal: AbortSignal.timeout(5000),
		});
		if (!res.ok) return '';
		const data = await res.json();
		return data.stargazers_count ? String(data.stargazers_count) : '';
	} catch {
		return '';
	}
}

export default async function nextConfig(phase) {
	if (phase !== PHASE_PRODUCTION_BUILD) return config;
	return {
		...config,
		env: { NEXT_PUBLIC_GITHUB_STARS: await fetchGitHubStars() },
	};
}
