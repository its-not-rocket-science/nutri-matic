<script lang="ts">
	import { onMount } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';

	let { children } = $props();

	onMount(async () => {
		if (auth.init()) {
			try {
				auth.setUser(await api.me());
			} catch {
				auth.logout();
			}
		}
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<nav>
	<a href="/">Nutri-Matic</a>
	{#if auth.isLoggedIn}
		<span class="muted">{auth.user?.email ?? ''}</span>
		<button type="button" onclick={() => auth.logout()}>Log out</button>
	{:else}
		<a href="/login">Log in</a>
		<a href="/register">Register</a>
	{/if}
</nav>

<main>
	{@render children()}
</main>

<style>
	main {
		max-width: 40rem;
		margin: 2rem auto;
		padding: 0 1rem;
		font-family: system-ui, sans-serif;
	}
	nav {
		max-width: 40rem;
		margin: 1rem auto 0;
		padding: 0 1rem;
		display: flex;
		align-items: center;
		gap: 1rem;
		font-family: system-ui, sans-serif;
		font-size: 0.9em;
	}
	nav a:first-child {
		font-weight: bold;
		margin-right: auto;
	}
	.muted {
		color: #666;
	}
</style>
