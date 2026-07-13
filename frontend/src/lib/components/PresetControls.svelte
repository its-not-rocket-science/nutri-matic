<script lang="ts">
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { FilterScope, NutrientFilterInput, SavedFilterPreset } from '$lib/types';

	let { scope, filters = $bindable([]) }: { scope: FilterScope; filters: NutrientFilterInput[] } =
		$props();

	let presets: SavedFilterPreset[] = $state([]);
	let selectedId: number | null = $state(null);
	let saving = $state(false);
	let error: string | null = $state(null);

	async function loadPresets() {
		if (!auth.isLoggedIn) return;
		try {
			presets = await api.listPresets(scope);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	$effect(() => {
		loadPresets();
	});

	async function handleSave() {
		const name = prompt('Name this filter preset:');
		if (!name) return;
		error = null;
		saving = true;
		try {
			await api.createPreset({ name, scope, filters });
			await loadPresets();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}

	function applySelected() {
		const preset = presets.find((p) => p.id === selectedId);
		if (preset) filters = preset.filters.map((f) => ({ ...f }));
	}

	async function handleDelete() {
		if (selectedId === null) return;
		try {
			await api.deletePreset(selectedId);
			selectedId = null;
			await loadPresets();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}
</script>

{#if auth.isLoggedIn}
	<div class="presets">
		{#if presets.length > 0}
			<select bind:value={selectedId} onchange={applySelected}>
				<option value={null}>Load a saved preset…</option>
				{#each presets as p (p.id)}
					<option value={p.id}>{p.name}</option>
				{/each}
			</select>
			{#if selectedId !== null}
				<button type="button" onclick={handleDelete}>Delete preset</button>
			{/if}
		{/if}
		<button type="button" onclick={handleSave} disabled={saving || filters.length === 0}>
			{saving ? 'Saving…' : 'Save current filters as preset'}
		</button>
	</div>
	{#if error}
		<p class="error">{error}</p>
	{/if}
{:else}
	<p class="muted"><a href="/login">Log in</a> to save filter presets.</p>
{/if}

<style>
	.presets {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
		margin: 0.5rem 0;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.error {
		color: #b00020;
	}
</style>
