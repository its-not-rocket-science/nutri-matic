<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import { activeProfile } from '$lib/activeProfile.svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { theme, type ThemeChoice } from '$lib/theme.svelte';

	let { children } = $props();

	// Runs during this component's own initialization, not inside onMount —
	// Svelte fires onMount bottom-up (child before parent), so a child page's
	// onMount guard (`if (!auth.isLoggedIn) goto('/login')`) would otherwise
	// run before this ever reads the token back from localStorage, bouncing
	// a logged-in user to /login on every hard refresh of a protected route.
	const hadStoredToken = auth.init() !== null;
	theme.init();

	const themeLabel: Record<ThemeChoice, string> = {
		system: 'Theme: System',
		light: 'Theme: Light',
		dark: 'Theme: Dark'
	};

	let navOpen = $state(false);

	type NavIcon =
		| 'today'
		| 'diary'
		| 'plan'
		| 'explore'
		| 'progress'
		| 'profile'
		| 'methodology'
		| 'about';

	interface NavLink {
		href: string;
		label: string;
	}
	interface NavGroup {
		label: string;
		icon: NavIcon;
		links: NavLink[];
	}

	// Every route lives in exactly one of these eight groups (Today / Diary /
	// Plan / Explore / Progress / Profile / Methodology / About) — the app
	// shell's whole job is making that grouping legible, not just listing
	// routes flat.
	const loggedInGroups: NavGroup[] = [
		{ label: 'Today', icon: 'today', links: [{ href: '/', label: 'Today' }] },
		{ label: 'Diary', icon: 'diary', links: [{ href: '/diary', label: 'Diary' }] },
		{
			label: 'Plan',
			icon: 'plan',
			links: [
				{ href: '/meal-plan', label: 'Meal Plan' },
				{ href: '/food-prices', label: 'Food Prices' }
			]
		},
		{
			label: 'Explore',
			icon: 'explore',
			links: [
				{ href: '/search', label: 'Search' },
				{ href: '/recipes', label: 'Recipes' },
				{ href: '/collections', label: 'Collections' }
			]
		},
		{
			label: 'Progress',
			icon: 'progress',
			links: [
				{ href: '/trends', label: 'Trends' },
				{ href: '/weight-log', label: 'Weight' }
			]
		},
		{
			label: 'Profile',
			icon: 'profile',
			links: [
				{ href: '/profile', label: 'Profile' },
				{ href: '/clinician', label: 'Clinician' }
			]
		},
		{ label: 'Methodology', icon: 'methodology', links: [{ href: '/methodology', label: 'Methodology' }] },
		{ label: 'About', icon: 'about', links: [{ href: '/about', label: 'About' }] }
	];

	const loggedOutGroups: NavGroup[] = [
		{ label: 'Methodology', icon: 'methodology', links: [{ href: '/methodology', label: 'Methodology' }] },
		{ label: 'About', icon: 'about', links: [{ href: '/about', label: 'About' }] }
	];

	const navGroups = $derived(auth.isLoggedIn ? loggedInGroups : loggedOutGroups);

	function isActive(href: string) {
		return page.url.pathname === href || (href !== '/' && page.url.pathname.startsWith(href + '/'));
	}

	function closeNav() {
		navOpen = false;
	}

	onMount(async () => {
		if (hadStoredToken) {
			try {
				auth.setUser(await api.me());
				activeProfile.setProfiles(await api.listProfiles());
			} catch {
				auth.logout();
			}
		}
	});

	async function handleSwitchProfile(e: Event) {
		const id = Number((e.target as HTMLSelectElement).value);
		activeProfile.setActive(id);
		// every page's own onMount re-fetches against the newly active
		// profile on next navigation; a full reload is the simplest way to
		// make the current page's already-loaded data refresh immediately too
		location.reload();
	}
</script>

<svelte:head>
	<title>Nutri-Matic — Nutritional Analysis &amp; Optimisation Instrument</title>
	<meta
		name="description"
		content="Nutri-Matic analyses and optimises nutritional quality — protein quality (DIAAS/PDCAAS), bioavailability-adjusted micronutrients, and computed food complementarity — not a calorie counter."
	/>
	<link rel="icon" href={favicon} />

	<!-- Open Graph / Twitter Card — image and description are static app-wide
	     defaults; individual routes (methodology, about, a food/recipe page)
	     override title/description via their own <svelte:head>. og:image
	     is intentionally a root-relative path: there's no production domain
	     configured yet (no PUBLIC_SITE_URL), and most crawlers resolve it
	     against the page URL correctly in practice — set an absolute URL
	     here once one exists. -->
	<meta property="og:site_name" content="Nutri-Matic" />
	<meta property="og:type" content="website" />
	<meta property="og:title" content="Nutri-Matic — Nutritional Analysis & Optimisation Instrument" />
	<meta
		property="og:description"
		content="Protein quality (DIAAS/PDCAAS), bioavailability-adjusted micronutrients, and computed food complementarity — not a calorie counter."
	/>
	<meta property="og:image" content="/og-image.png" />
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content="Nutri-Matic — Nutritional Analysis & Optimisation Instrument" />
	<meta
		name="twitter:description"
		content="Protein quality (DIAAS/PDCAAS), bioavailability-adjusted micronutrients, and computed food complementarity — not a calorie counter."
	/>
	<meta name="twitter:image" content="/og-image.png" />
</svelte:head>

<a class="skip-link" href="#main-content">Skip to content</a>

<div class="shell">
	<div class="topbar no-print">
		<button
			type="button"
			class="nav-toggle"
			aria-expanded={navOpen}
			aria-controls="sidebar"
			onclick={() => (navOpen = !navOpen)}
		>
			<span class="sr-only">{navOpen ? 'Close menu' : 'Open menu'}</span>
			<span class="nav-toggle-icon" class:open={navOpen} aria-hidden="true"></span>
		</button>
		<a class="brand" href="/">
			<svg class="brand-mark" width="24" height="24" viewBox="0 0 150 150" aria-hidden="true">
				<circle cx="75" cy="75" r="62" fill="none" stroke="currentColor" stroke-width="6" />
				<line x1="75" y1="75" x2="100" y2="38" stroke="var(--color-accent)" stroke-width="9" stroke-linecap="round" />
				<circle cx="75" cy="75" r="10" fill="var(--color-accent)" />
			</svg>
			<span class="brand-word">Nutri<span class="dot">&middot;</span>Matic</span>
		</a>
	</div>

	{#if navOpen}
		<button type="button" class="backdrop" aria-label="Close menu" onclick={closeNav}></button>
	{/if}

	<aside class="sidebar no-print" id="sidebar" class:open={navOpen}>
		<div class="sidebar-brand">
			<a class="brand" href="/" onclick={closeNav}>
				<svg class="brand-mark" width="28" height="28" viewBox="0 0 150 150" aria-hidden="true">
					<circle cx="75" cy="75" r="62" fill="none" stroke="currentColor" stroke-width="6" />
					<line x1="75" y1="75" x2="100" y2="38" stroke="var(--color-accent)" stroke-width="9" stroke-linecap="round" />
					<circle cx="75" cy="75" r="10" fill="var(--color-accent)" />
				</svg>
				<span class="brand-word">Nutri<span class="dot">&middot;</span>Matic</span>
			</a>
		</div>

		<nav aria-label="Main">
			{#each navGroups as group (group.label)}
				<div class="nav-group">
					{#if group.links.length > 1}
						<span class="nav-group-label">
							<svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
								{@render navIconPath(group.icon)}
							</svg>
							{group.label}
						</span>
						{#each group.links as link (link.href)}
							<a
								class="nav-link nav-link-sub"
								href={link.href}
								aria-current={isActive(link.href) ? 'page' : undefined}
								onclick={closeNav}
							>
								{link.label}
							</a>
						{/each}
					{:else}
						<a
							class="nav-link"
							href={group.links[0].href}
							aria-current={isActive(group.links[0].href) ? 'page' : undefined}
							onclick={closeNav}
						>
							<svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
								{@render navIconPath(group.icon)}
							</svg>
							{group.label}
						</a>
					{/if}
				</div>
			{/each}
		</nav>

		<div class="sidebar-footer">
			<button type="button" class="btn btn-secondary theme-toggle-btn" onclick={() => theme.cycle()}>
				<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
					{#if theme.choice === 'light'}
						<circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="1.75" />
						<g stroke="currentColor" stroke-width="1.75" stroke-linecap="round">
							<line x1="12" y1="2.5" x2="12" y2="5" />
							<line x1="12" y1="19" x2="12" y2="21.5" />
							<line x1="2.5" y1="12" x2="5" y2="12" />
							<line x1="19" y1="12" x2="21.5" y2="12" />
							<line x1="5.1" y1="5.1" x2="6.9" y2="6.9" />
							<line x1="17.1" y1="17.1" x2="18.9" y2="18.9" />
							<line x1="5.1" y1="18.9" x2="6.9" y2="17.1" />
							<line x1="17.1" y1="6.9" x2="18.9" y2="5.1" />
						</g>
					{:else if theme.choice === 'dark'}
						<path
							d="M20 14.5 A8.5 8.5 0 1 1 9.5 4 A7 7 0 0 0 20 14.5"
							fill="none"
							stroke="currentColor"
							stroke-width="1.75"
							stroke-linejoin="round"
						/>
					{:else}
						<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.75" />
						<path d="M12 3 A9 9 0 0 1 12 21 Z" fill="currentColor" />
					{/if}
				</svg>
				{themeLabel[theme.choice]}
			</button>
			{#if auth.isLoggedIn}
				{#if activeProfile.list.length > 1}
					<label class="profile-switcher-label" for="active-profile-select">
						<span class="sr-only">Active profile</span>
						<select
							id="active-profile-select"
							class="profile-switcher-select"
							value={activeProfile.id ?? ''}
							onchange={handleSwitchProfile}
						>
							{#each activeProfile.list as p (p.id)}
								<option value={p.id}>{p.name}{p.is_account_owner ? ' (you)' : ''}</option>
							{/each}
						</select>
					</label>
				{/if}
				<span class="user-email muted">{auth.user?.email ?? ''}</span>
				<button type="button" class="btn btn-secondary logout-btn" onclick={() => auth.logout()}>Log out</button>
			{:else}
				<a class="nav-link" href="/login" onclick={closeNav}>Log in</a>
				<a class="nav-link" href="/register" onclick={closeNav}>Register</a>
			{/if}
		</div>
	</aside>

	<main id="main-content">
		{@render children()}
	</main>
</div>

{#snippet navIconPath(icon: NavIcon)}
	{#if icon === 'today'}
		<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.75" />
		<line x1="12" y1="12" x2="16" y2="7" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
	{:else if icon === 'diary'}
		<rect x="5" y="4" width="14" height="17" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.75" />
		<line x1="8" y1="9" x2="16" y2="9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
		<line x1="8" y1="13" x2="16" y2="13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
		<line x1="8" y1="17" x2="13" y2="17" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
	{:else if icon === 'plan'}
		<rect x="4" y="5" width="16" height="15" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.75" />
		<line x1="4" y1="9.5" x2="20" y2="9.5" stroke="currentColor" stroke-width="1.75" />
		<line x1="8" y1="3" x2="8" y2="6.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
		<line x1="16" y1="3" x2="16" y2="6.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
	{:else if icon === 'explore'}
		<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.75" />
		<line x1="12" y1="4.5" x2="12" y2="7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
		<line x1="12" y1="17" x2="12" y2="19.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
		<line x1="4.5" y1="12" x2="7" y2="12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
		<line x1="17" y1="12" x2="19.5" y2="12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
		<circle cx="12" cy="12" r="1.5" fill="currentColor" />
	{:else if icon === 'progress'}
		<polyline
			points="4,17 9,11 13,14 20,5"
			fill="none"
			stroke="currentColor"
			stroke-width="1.75"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
		<circle cx="20" cy="5" r="1.6" fill="currentColor" />
	{:else if icon === 'profile'}
		<circle cx="12" cy="8" r="3.75" fill="none" stroke="currentColor" stroke-width="1.75" />
		<path d="M5.5,20 a6.5,5.5 0 0 1 13,0" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
	{:else if icon === 'methodology'}
		<polyline
			points="9,3 9,9 4,19 20,19 15,9 15,3"
			fill="none"
			stroke="currentColor"
			stroke-width="1.75"
			stroke-linejoin="round"
			stroke-linecap="round"
		/>
		<line x1="7.5" y1="3" x2="16.5" y2="3" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
		<line x1="6.5" y1="15.5" x2="17.5" y2="15.5" stroke="currentColor" stroke-width="1.5" />
	{:else if icon === 'about'}
		<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.75" />
		<line x1="12" y1="10.5" x2="12" y2="16.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
		<circle cx="12" cy="7.3" r="1.1" fill="currentColor" />
	{/if}
{/snippet}

<style>
	.skip-link {
		position: absolute;
		left: -999px;
		top: 0;
		background: var(--color-primary);
		color: var(--color-on-primary);
		padding: var(--space-2) var(--space-4);
		z-index: 100;
		border-radius: 0 0 var(--radius-sm) 0;
	}
	.skip-link:focus {
		left: 0;
	}

	.shell {
		display: flex;
		min-height: 100vh;
	}

	.brand {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text);
		text-decoration: none;
	}
	.brand-mark {
		color: var(--color-primary);
		flex-shrink: 0;
	}
	.brand-word {
		font-family: var(--font-display);
		text-transform: uppercase;
		font-weight: var(--font-weight-bold);
		font-size: var(--font-size-md);
		letter-spacing: 0.02em;
	}
	.brand-word .dot {
		display: inline-block;
		margin: 0 0.22em;
		color: var(--color-accent-text);
	}

	/* Topbar: mobile-only strip holding the menu toggle + brand. Hidden on
	   desktop, where the sidebar carries its own brand lockup instead. */
	.topbar {
		display: none;
		align-items: center;
		gap: var(--space-3);
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		z-index: 40;
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border);
		padding: var(--space-3) var(--space-4);
	}

	.nav-toggle {
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		width: 2.75rem;
		height: 2.75rem;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.nav-toggle-icon,
	.nav-toggle-icon::before,
	.nav-toggle-icon::after {
		display: block;
		width: 1.25rem;
		height: 2px;
		background: var(--color-text);
		border-radius: var(--radius-full);
		transition:
			transform 0.2s ease,
			opacity 0.2s ease,
			top 0.2s ease;
	}
	.nav-toggle-icon {
		position: relative;
	}
	.nav-toggle-icon::before,
	.nav-toggle-icon::after {
		content: '';
		position: absolute;
		left: 0;
	}
	.nav-toggle-icon::before {
		top: -6px;
	}
	.nav-toggle-icon::after {
		top: 6px;
	}
	/* Open state: hamburger folds into an X */
	.nav-toggle-icon.open {
		background: transparent;
	}
	.nav-toggle-icon.open::before {
		top: 0;
		transform: rotate(45deg);
	}
	.nav-toggle-icon.open::after {
		top: 0;
		transform: rotate(-45deg);
	}

	.backdrop {
		position: fixed;
		inset: 0;
		background: rgba(20, 16, 10, 0.4);
		border: none;
		z-index: 45;
		cursor: pointer;
	}

	.sidebar {
		width: 16rem;
		flex-shrink: 0;
		background: var(--color-surface);
		border-right: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		padding: var(--space-5) var(--space-4);
	}

	.sidebar-brand {
		margin-bottom: var(--space-6);
	}

	nav {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.nav-group {
		display: flex;
		flex-direction: column;
	}

	.nav-group-label {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-family: var(--font-display);
		text-transform: uppercase;
		font-size: var(--font-size-xs);
		letter-spacing: 0.05em;
		color: var(--color-text-subtle);
		padding: var(--space-1) var(--space-2);
	}

	.nav-link {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
		text-decoration: none;
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--font-size-sm);
		min-height: 2.75rem;
		transition:
			background-color 0.15s ease,
			color 0.15s ease;
	}
	.nav-link-sub {
		padding-left: var(--space-6);
	}
	.nav-icon {
		flex-shrink: 0;
	}

	.nav-link:hover {
		color: var(--color-text);
		background: var(--color-surface-muted);
	}

	.nav-link[aria-current='page'] {
		color: var(--color-primary);
		background: var(--color-primary-subtle);
		font-weight: var(--font-weight-medium);
	}

	.sidebar-footer {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-top: var(--space-4);
		border-top: 1px solid var(--color-border);
	}
	.profile-switcher-label {
		display: block;
		padding: 0 var(--space-2);
	}
	.profile-switcher-select {
		width: 100%;
	}
	.user-email {
		padding: 0 var(--space-2);
		word-break: break-word;
	}
	.logout-btn {
		align-self: flex-start;
	}
	.theme-toggle-btn {
		align-self: flex-start;
		justify-content: flex-start;
		gap: var(--space-2);
	}

	main {
		flex: 1;
		min-width: 0;
		max-width: var(--layout-max-width);
		margin: var(--space-6) auto;
		padding: 0 var(--space-4);
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	/* Below this, the sidebar becomes an off-canvas drawer opened by the
	   mobile topbar's toggle, matching the PWA's phone-first use case. */
	@media (max-width: 60rem) {
		.topbar {
			display: flex;
		}
		.sidebar-brand {
			display: none;
		}
		.sidebar {
			position: fixed;
			inset: 0 auto 0 0;
			z-index: 50;
			transform: translateX(-100%);
			transition: transform 0.2s ease;
			box-shadow: var(--shadow-lg);
		}
		.sidebar.open {
			transform: translateX(0);
		}
		main {
			margin-top: calc(var(--space-6) + 3.5rem);
		}
	}

	@media print {
		.no-print {
			display: none !important;
		}
		main {
			margin-top: 0;
		}
	}
</style>
