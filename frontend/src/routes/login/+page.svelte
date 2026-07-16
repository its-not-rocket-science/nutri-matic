<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';

	let email = $state('');
	let password = $state('');
	let error: string | null = $state(null);
	let submitting = $state(false);
	let demoLoading = $state(false);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			const { access_token } = await api.login(email, password);
			auth.setToken(access_token);
			auth.setUser(await api.me());
			await goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			submitting = false;
		}
	}

	async function handleTryDemo() {
		demoLoading = true;
		error = null;
		try {
			const { access_token } = await api.startDemo();
			auth.setToken(access_token);
			auth.setUser(await api.me());
			await goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			demoLoading = false;
		}
	}
</script>

<h1>Log in</h1>
<p><a href="/">&larr; Back</a></p>

<form class="card auth-form" onsubmit={handleSubmit}>
	<div class="field">
		<label for="email">Email</label>
		<input id="email" type="email" bind:value={email} required />
	</div>
	<div class="field">
		<label for="password">Password</label>
		<input id="password" type="password" bind:value={password} required />
	</div>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<button type="submit" class="btn btn-primary" disabled={submitting}>
		{submitting ? 'Logging in…' : 'Log in'}
	</button>
</form>

<p>No account? <a href="/register">Register</a></p>
<p>
	Not ready to sign up?
	<button type="button" class="btn-plain-link" disabled={demoLoading} onclick={handleTryDemo}>
		{demoLoading ? 'Setting up…' : 'Try the demo'}
	</button>
</p>

<style>
	.auth-form {
		max-width: 24rem;
	}
	.auth-form .field:last-of-type {
		margin-bottom: var(--space-4);
	}
	.btn-plain-link {
		background: none;
		border: none;
		padding: 0;
		color: var(--color-primary);
		text-decoration: underline;
	}
</style>
