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

<form onsubmit={handleSubmit}>
	<label>
		Name
		<input type="text" bind:value={name} required />
	</label>

	<label>
		Protein (g per 100g)
		<input type="number" step="any" min="0" bind:value={proteinPer100g} required />
	</label>

	<fieldset>
		<legend>Amino acids (mg per g protein)</legend>
		{#each aaKeys as key (key)}
			<label>
				{AMINO_ACID_LABELS[key]}
				<input type="number" step="any" min="0" bind:value={aminoAcids[key]} required />
			</label>
		{/each}
	</fieldset>

	<fieldset>
		<legend>Digestibility</legend>
		<label>
			DIAAS digestibility (uniform SID coefficient, 0–1)
			<input type="number" step="any" min="0" max="1" bind:value={diaasDigestibility} />
		</label>
		<label>
			PDCAAS overall digestibility (0–1)
			<input type="number" step="any" min="0" max="1" bind:value={pdcaasDigestibility} />
		</label>
	</fieldset>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<button type="submit" disabled={submitting}>{submitting ? 'Saving…' : 'Save food'}</button>
</form>

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 32rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	fieldset {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.error {
		color: #b00020;
	}
</style>
