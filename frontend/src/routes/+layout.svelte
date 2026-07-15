<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';

	let { children } = $props();

	// Runs during this component's own initialization, not inside onMount —
	// Svelte fires onMount bottom-up (child before parent), so a child page's
	// onMount guard (`if (!auth.isLoggedIn) goto('/login')`) would otherwise
	// run before this ever reads the token back from localStorage, bouncing
	// a logged-in user to /login on every hard refresh of a protected route.
	const hadStoredToken = auth.init() !== null;

	let navOpen = $state(false);

	const navLinks = $derived(
		auth.isLoggedIn
			? [
					{ href: '/diary', label: 'Diary' },
					{ href: '/trends', label: 'Trends' },
					{ href: '/meal-plan', label: 'Meal Plan' },
					{ href: '/food-prices', label: 'Food Prices' },
					{ href: '/recipes', label: 'Recipes' },
					{ href: '/weight-log', label: 'Weight' },
					{ href: '/clinician', label: 'Clinician' },
					{ href: '/methodology', label: 'Data & Methodology' },
					{ href: '/profile', label: 'Profile' }
				]
			: [
					{ href: '/methodology', label: 'Data & Methodology' },
					{ href: '/login', label: 'Log in' },
					{ href: '/register', label: 'Register' }
				]
	);

	function isActive(href: string) {
		return page.url.pathname === href || page.url.pathname.startsWith(href + '/');
	}

	onMount(async () => {
		if (hadStoredToken) {
			try {
				auth.setUser(await api.me());
			} catch {
				auth.logout();
			}
		}
	});
</script>

<svelte:head>
	<title>Nutri-Matic — Nutrition Analysis &amp; Optimisation Engine</title>
	<meta
		name="description"
		content="Nutri-Matic analyses and optimises nutritional quality — protein quality (DIAAS/PDCAAS), bioavailability-adjusted micronutrients, and computed food complementarity — not a calorie counter."
	/>
	<link rel="icon" href={favicon} />
</svelte:head>

<header class="site-header">
	<div class="header-bar">
		<a class="brand" href="/">Nutri-Matic</a>

		<button
			type="button"
			class="nav-toggle"
			aria-expanded={navOpen}
			aria-controls="primary-nav"
			onclick={() => (navOpen = !navOpen)}
		>
			<span class="sr-only">{navOpen ? 'Close menu' : 'Open menu'}</span>
			<span class="nav-toggle-icon" aria-hidden="true"></span>
		</button>
	</div>

	<nav id="primary-nav" aria-label="Main" class:open={navOpen}>
		{#each navLinks as link (link.href)}
			<a href={link.href} aria-current={isActive(link.href) ? 'page' : undefined} onclick={() => (navOpen = false)}>
				{link.label}
			</a>
		{/each}
		{#if auth.isLoggedIn}
			<span class="user-email muted">{auth.user?.email ?? ''}</span>
			<button type="button" class="logout-btn" onclick={() => auth.logout()}>Log out</button>
		{/if}
	</nav>
</header>

<main>
	{@render children()}
</main>

<style>
	main {
		max-width: var(--layout-max-width);
		margin: var(--space-6) auto;
		padding: 0 var(--space-4);
	}

	.site-header {
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border);
	}

	.header-bar {
		max-width: var(--layout-max-width);
		margin: 0 auto;
		padding: var(--space-3) var(--space-4);
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.brand {
		font-weight: var(--font-weight-bold);
		font-size: var(--font-size-md);
		color: var(--color-text);
		text-decoration: none;
	}

	.nav-toggle {
		display: none;
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		width: 2.75rem;
		height: 2.75rem;
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

	nav {
		max-width: var(--layout-max-width);
		margin: 0 auto;
		padding: 0 var(--space-4) var(--space-3);
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-4);
		font-size: var(--font-size-sm);
	}

	nav a {
		color: var(--color-text-muted);
		text-decoration: none;
		padding: var(--space-1) 0;
		border-bottom: 2px solid transparent;
	}

	nav a:hover {
		color: var(--color-text);
	}

	nav a[aria-current='page'] {
		color: var(--color-primary);
		border-bottom-color: var(--color-primary);
		font-weight: var(--font-weight-medium);
	}

	.user-email {
		margin-left: auto;
	}

	.logout-btn {
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-3);
		color: var(--color-text);
	}
	.logout-btn:hover {
		border-color: var(--color-border-strong);
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

	@media (max-width: 40rem) {
		.nav-toggle {
			display: flex;
		}
		nav {
			display: none;
			flex-direction: column;
			align-items: stretch;
			gap: 0;
			padding-bottom: var(--space-3);
		}
		nav.open {
			display: flex;
		}
		nav a {
			padding: var(--space-3) 0;
			border-bottom: 1px solid var(--color-border);
		}
		nav a[aria-current='page'] {
			border-bottom-color: var(--color-primary);
		}
		.user-email {
			margin-left: 0;
			padding: var(--space-2) 0;
		}
		.logout-btn {
			margin: var(--space-2) 0;
			align-self: flex-start;
		}
	}

	@media print {
		.site-header {
			display: none;
		}
	}
</style>
