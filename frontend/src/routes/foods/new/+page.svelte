<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { AMINO_ACID_LABELS, type AminoAcidProfile } from '$lib/types';

	let name = $state('');
	let proteinPer100g = $state<number | null>(null);
	let aminoAcids = $state<Record<keyof AminoAcidProfile, number | null>>({
		histidine: null,
		isoleucine: null,
		leucine: null,
		lysine: null,
		met_cys: null,
		phe_tyr: null,
		threonine: null,
		tryptophan: null,
		valine: null
	});
	let diaasDigestibility = $state<number | null>(null);
	let pdcaasDigestibility = $state<number | null>(null);
	let error: string | null = $state(null);
	let submitting = $state(false);

	const aaKeys = Object.keys(AMINO_ACID_LABELS) as (keyof AminoAcidProfile)[];

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = null;

		if (!name || proteinPer100g === null) {
			error = 'Name and protein content are required.';
			return;
		}
		const missingAA = aaKeys.find((k) => aminoAcids[k] === null);
		if (missingAA) {
			error = `Missing amino acid value: ${AMINO_ACID_LABELS[missingAA]}`;
			return;
		}
		if (diaasDigestibility === null && pdcaasDigestibility === null) {
			error = 'Provide at least one digestibility value (DIAAS and/or PDCAAS).';
			return;
		}

		const profile = Object.fromEntries(
			aaKeys.map((k) => [k, aminoAcids[k]])
		) as unknown as AminoAcidProfile;
		const digestibilityDiaas =
			diaasDigestibility === null
				? null
				: (Object.fromEntries(
						aaKeys.map((k) => [k, diaasDigestibility])
					) as unknown as AminoAcidProfile);

		submitting = true;
		try {
			const food = await api.createFood({
				name,
				protein_g_per_100g: proteinPer100g,
				amino_acids: profile,
				digestibility_diaas: digestibilityDiaas,
				digestibility_pdcaas: pdcaasDigestibility
			});
			await goto(`/foods/${food.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			submitting = false;
		}
	}
</script>

<h1>Add a food</h1>
<p><a href="/">&larr; Back</a></p>

<form class="card food-form" onsubmit={handleSubmit}>
	<div class="field">
		<label for="food-name">Name</label>
		<input id="food-name" type="text" bind:value={name} required />
	</div>

	<div class="field">
		<label for="food-protein">Protein (g per 100g)</label>
		<input id="food-protein" type="number" step="any" min="0" bind:value={proteinPer100g} required />
	</div>

	<fieldset>
		<legend>Amino acids (mg per g protein)</legend>
		<div class="aa-grid">
			{#each aaKeys as key (key)}
				<div class="field">
					<label for="aa-{key}">{AMINO_ACID_LABELS[key]}</label>
					<input id="aa-{key}" type="number" step="any" min="0" bind:value={aminoAcids[key]} required />
				</div>
			{/each}
		</div>
	</fieldset>

	<fieldset>
		<legend>Digestibility</legend>
		<div class="field">
			<label for="diaas-digestibility">DIAAS digestibility (uniform SID coefficient, 0–1)</label>
			<input id="diaas-digestibility" type="number" step="any" min="0" max="1" bind:value={diaasDigestibility} />
		</div>
		<div class="field">
			<label for="pdcaas-digestibility">PDCAAS overall digestibility (0–1)</label>
			<input id="pdcaas-digestibility" type="number" step="any" min="0" max="1" bind:value={pdcaasDigestibility} />
		</div>
	</fieldset>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<button type="submit" class="btn btn-primary" disabled={submitting}>
		{submitting ? 'Saving…' : 'Save food'}
	</button>
</form>

<style>
	.food-form {
		max-width: 34rem;
	}
	fieldset {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-4);
		margin: 0 0 var(--space-4);
	}
	legend {
		font-size: var(--font-size-sm);
		font-weight: var(--font-weight-medium);
		padding: 0 var(--space-2);
	}
	.aa-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
		gap: 0 var(--space-4);
	}
</style>
