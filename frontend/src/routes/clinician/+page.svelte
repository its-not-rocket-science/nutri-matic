<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import type { ClinicianClientSummary, ClinicianLink, ClinicianNote } from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	let error: string | null = $state(null);
	let loading = $state(true);

	let clients: ClinicianLink[] = $state([]);
	let pendingInvites: ClinicianLink[] = $state([]);

	let inviteEmail = $state('');
	let inviting = $state(false);

	let selectedClientEmail: string | null = $state(null);
	let selectedClientUserId: number | null = $state(null);
	let summary: ClinicianClientSummary | null = $state(null);
	let notes: ClinicianNote[] = $state([]);
	let summaryDate = $state(toIsoDate(new Date()));
	let loadingSummary = $state(false);

	let newNoteText = $state('');
	let savingNote = $state(false);

	async function loadClients() {
		clients = await api.listClinicianClients();
	}

	async function loadPendingInvites() {
		pendingInvites = await api.listPendingClinicianInvites();
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			await Promise.all([loadClients(), loadPendingInvites()]);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function handleInvite(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		if (!inviteEmail.trim()) return;
		inviting = true;
		try {
			await api.inviteClinicianClient(inviteEmail.trim());
			inviteEmail = '';
			await loadClients();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			inviting = false;
		}
	}

	async function handleAcceptInvite(linkId: number) {
		error = null;
		try {
			await api.acceptClinicianInvite(linkId);
			await Promise.all([loadPendingInvites(), loadClients()]);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleDeclineInvite(linkId: number) {
		error = null;
		try {
			await api.declineClinicianInvite(linkId);
			await loadPendingInvites();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function selectClient(link: ClinicianLink) {
		error = null;
		selectedClientEmail = link.client_email;
		selectedClientUserId = link.client_user_id;
		await loadClientDetail();
	}

	async function loadClientDetail() {
		if (selectedClientUserId === null) return;
		loadingSummary = true;
		error = null;
		try {
			summary = await api.getClinicianClientSummary(selectedClientUserId, summaryDate);
			notes = await api.listClinicianNotes(selectedClientUserId);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingSummary = false;
		}
	}

	async function handleRevoke(clientUserId: number) {
		error = null;
		try {
			await api.revokeClinicianClient(clientUserId);
			if (selectedClientUserId === clientUserId) {
				selectedClientUserId = null;
				selectedClientEmail = null;
				summary = null;
			}
			await loadClients();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleAddNote(e: SubmitEvent) {
		e.preventDefault();
		if (selectedClientUserId === null || !newNoteText.trim()) return;
		error = null;
		savingNote = true;
		try {
			await api.createClinicianNote(selectedClientUserId, newNoteText.trim());
			newNoteText = '';
			notes = await api.listClinicianNotes(selectedClientUserId);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			savingNote = false;
		}
	}
</script>

<h1>Clinician dashboard</h1>
<p><a href="/">&larr; Back</a></p>
<p class="muted">
	Manage clients who've explicitly granted you access to their nutrition data. This app has no
	license-verification mechanism — "clinician" here means any account a client has chosen to
	share their data with, not a verified professional credential.
</p>

{#if error}
	<p class="error">{error}</p>
{/if}

{#if loading}
	<p class="muted">Calibrating…</p>
{:else}
	<form onsubmit={handleInvite} class="invite-form">
		<h3>Invite a client</h3>
		<p class="muted">
			The client must already have a Nutri-Matic account, and must explicitly accept before you
			get any access to their data.
		</p>
		<label>
			Client email
			<input type="email" bind:value={inviteEmail} required />
		</label>
		<button type="submit" disabled={inviting}>{inviting ? 'Sending…' : 'Send invite'}</button>
	</form>

	{#if pendingInvites.length > 0}
		<section>
			<h3>Invites sent to you</h3>
			<ul class="entries">
				{#each pendingInvites as invite (invite.id)}
					<li>
						<span>{invite.clinician_email} wants access to your data</span>
						<button type="button" onclick={() => handleAcceptInvite(invite.id)}>Accept</button>
						<button type="button" onclick={() => handleDeclineInvite(invite.id)}>Decline</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	<section>
		<h3>Your clients ({clients.length})</h3>
		{#if clients.length === 0}
			<p class="muted">No active clients yet — invite one above.</p>
		{:else}
			<ul class="entries">
				{#each clients as link (link.id)}
					<li class:selected={selectedClientEmail === link.client_email}>
						<span>{link.client_email}</span>
						<button type="button" onclick={() => selectClient(link)}>View</button>
						<button type="button" onclick={() => handleRevoke(link.client_user_id)}>Revoke</button>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	{#if selectedClientEmail}
		<section class="client-detail">
			<h3>{selectedClientEmail}</h3>
			<label>
				Date
				<input
					type="date"
					bind:value={summaryDate}
					onchange={loadClientDetail}
				/>
			</label>

			{#if loadingSummary}
				<p class="muted">Calibrating…</p>
			{:else if summary}
				{#if summary.day.entries.length === 0}
					<p class="muted">Nothing logged this day.</p>
				{:else}
					<NutrientBars nutrients={summary.day.nutrients} per="per day" />
				{/if}
			{/if}

			<h4>Notes (private to you)</h4>
			<ul class="entries">
				{#each notes as note (note.id)}
					<li class="note">
						<p>{note.note_text}</p>
						<span class="muted">{new Date(note.created_at).toLocaleString()}</span>
					</li>
				{/each}
			</ul>
			<form onsubmit={handleAddNote} class="note-form">
				<textarea bind:value={newNoteText} placeholder="Add a private note…" required></textarea>
				<button type="submit" disabled={savingNote}>{savingNote ? 'Saving…' : 'Add note'}</button>
			</form>
		</section>
	{/if}
{/if}

<style>
	.error {
		color: var(--color-danger);
	}
	.muted {
		color: var(--color-text-muted);
		font-size: 0.9em;
	}
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: 0.4rem 0;
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.entries li.selected {
		font-weight: bold;
	}
	.invite-form,
	.note-form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 28rem;
		margin: 1.5rem 0;
		padding: 1rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
	}
	.note-form {
		margin: 0.75rem 0 0;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.client-detail {
		margin-top: 1.5rem;
		padding: 1rem;
		border: 1px solid var(--color-border);
		border-radius: 4px;
	}
	.note {
		flex-direction: column;
		align-items: flex-start;
	}
</style>
