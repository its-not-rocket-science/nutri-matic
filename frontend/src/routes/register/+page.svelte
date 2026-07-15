<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';

	let email = $state('');
	let password = $state('');
	let error: string | null = $state(null);
	let submitting = $state(false);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			const { access_token } = await api.register(email, password);
			auth.setToken(access_token);
			auth.setUser(await api.me());
			await goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			submitting = false;
		}
	}
</script>

<h1>Register</h1>
<p><a href="/">&larr; Back</a></p>

<form class="card auth-form" onsubmit={handleSubmit}>
	<div class="field">
		<label for="email">Email</label>
		<input id="email" type="email" bind:value={email} required />
	</div>
	<div class="field">
		<label for="password">Password</label>
		<input id="password" type="password" bind:value={password} required minlength="8" />
	</div>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<button type="submit" class="btn btn-primary" disabled={submitting}>
		{submitting ? 'Creating account…' : 'Register'}
	</button>
</form>

<p>Already have an account? <a href="/login">Log in</a></p>

<style>
	.auth-form {
		max-width: 24rem;
	}
	.auth-form .field:last-of-type {
		margin-bottom: var(--space-4);
	}
</style>
