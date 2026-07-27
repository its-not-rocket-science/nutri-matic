// Public-launch hardening prompt 5: the single canonical public origin
// — used for <link rel="canonical">, absolute Open Graph/Twitter URLs,
// the sitemap, and hooks.server.ts's alias redirect. One constant
// rather than each call site hard-coding the domain separately, so
// there's exactly one place to change if the canonical domain ever
// does. Not env-configurable: unlike VITE_API_URL (which genuinely
// differs per environment/backend), there is exactly one real
// canonical public origin for this app, in every environment that
// matters for SEO/redirect purposes — a config knob here would just be
// a second place this could drift from reality.
export const CANONICAL_ORIGIN = 'https://nutri-matic.uk';

// Known public aliases that should permanently redirect to
// CANONICAL_ORIGIN — see hooks.server.ts. Deliberately just the one
// confirmed, live stable alias (verified via a real HTTP request, not
// assumed) — a per-deployment preview hostname
// (nutri-matic-<hash>-pauls-projects-24d18deb.vercel.app) is NEVER in
// this list and must never be added to it: redirecting those would
// break preview deployments entirely.
export const REDIRECT_FROM_HOSTS = ['nutri-matic.vercel.app'];

// Public, indexable marketing/entry routes only — deliberately excludes
// every authenticated-app route (diary, meal-plan, profile, search,
// recipes, collections, trends, weight-log, food-prices, clinician,
// foods/*) and anything demo-account-specific, per the prompt's explicit
// instruction. Used by both the sitemap and robots.txt's intent (see
// static/robots.txt) — keep the two in sync if this list changes.
export const PUBLIC_ROUTES = ['/', '/about', '/methodology', '/login', '/register'];

export function canonicalUrl(pathname: string): string {
	return `${CANONICAL_ORIGIN}${pathname}`;
}
