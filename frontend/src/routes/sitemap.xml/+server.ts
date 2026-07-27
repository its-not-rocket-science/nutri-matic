import { CANONICAL_ORIGIN, PUBLIC_ROUTES } from '$lib/site';

// Public-launch hardening prompt 5. Only the same genuinely public
// routes robots.txt allows — see site.ts's PUBLIC_ROUTES docstring for
// why everything else (every authenticated-app route, anything
// demo-account-specific) is deliberately excluded.
export function GET() {
	const urls = PUBLIC_ROUTES.map(
		(path) => `  <url><loc>${CANONICAL_ORIGIN}${path}</loc></url>`
	).join('\n');
	const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;

	return new Response(body, {
		headers: { 'Content-Type': 'application/xml' }
	});
}
