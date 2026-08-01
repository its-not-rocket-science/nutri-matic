<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import type { ClinicianInvitePreview } from '$lib/types';

	const token = page.params.token ?? '';

	let preview: ClinicianInvitePreview | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			preview = await api.getClinicianInvitePreview(token);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>You've been invited to Nutri-Matic</title>
</svelte:head>

<p class="no-print"><a href="/">&larr; Back</a></p>

{#if loading}
	<p class="muted">Calibrating…</p>
{:else if error || !preview}
	<h1>Invite not found</h1>
	<p class="muted">
		This invite link isn't valid — it may have already been used, or the clinician may have
		revoked it. Ask them to send a new one, or
		<a href="/register">register</a> directly.
	</p>
{:else}
	<h1>{preview.clinician_email} invited you to Nutri-Matic</h1>
	<blockquote class="card invite-message">{preview.message}</blockquote>
	<p class="muted">
		Once you join, you'll be able to review and accept — or decline — their request for access
		to your nutrition data from your <a href="/clinician">clinician dashboard</a>.
	</p>
	<div class="actions">
		<a class="btn btn-primary" href="/register?email={encodeURIComponent(preview.invite_email)}">
			Create an account
		</a>
		<a class="btn btn-secondary" href="/login?email={encodeURIComponent(preview.invite_email)}">
			Already have an account? Log in
		</a>
	</div>
{/if}

<style>
	.invite-message {
		max-width: 36rem;
		margin: var(--space-4) 0;
		padding: var(--space-4);
		white-space: pre-wrap;
		border-left: 3px solid var(--color-primary);
	}
	.actions {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
</style>
