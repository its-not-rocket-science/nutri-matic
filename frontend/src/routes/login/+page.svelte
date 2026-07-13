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
			const { access_token } = await api.login(email, password);
			auth.setToken(access_token);
			auth.setUser(await api.me());
			await goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			submitting = false;
		}
	}
</script>

<h1>Log in</h1>
<p><a href="/">&larr; Back</a></p>

<form onsubmit={handleSubmit}>
	<label>
		Email
		<input type="email" bind:value={email} required />
	</label>
	<label>
		Password
		<input type="password" bind:value={password} required />
	</label>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<button type="submit" disabled={submitting}>{submitting ? 'Logging in…' : 'Log in'}</button>
</form>

<p>No account? <a href="/register">Register</a></p>

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 24rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.error {
		color: #b00020;
	}
</style>
