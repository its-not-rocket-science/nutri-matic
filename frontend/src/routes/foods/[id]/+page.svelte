<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import type { Complement, Food, FoodProvenance, NutrientAmount, Score } from '$lib/types';

	const foodId = Number(page.params.id);

	let food: Food | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let diaasComplement: Complement | null = $state(null);
	let pdcaasComplement: Complement | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	let provenance: FoodProvenance | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			food = await api.getFood(foodId);
			const [diaas, pdcaas, nutrientResult, provenanceResult] = await Promise.allSettled([
				food.digestibility_diaas ? api.scoreFood(foodId, 'diaas') : Promise.reject(),
				food.digestibility_pdcaas !== null ? api.scoreFood(foodId, 'pdcaas') : Promise.reject(),
				api.getNutrients(foodId),
				api.getFoodProvenance(foodId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
			if (provenanceResult.status === 'fulfilled') provenance = provenanceResult.value;

			const [diaasComp, pdcaasComp] = await Promise.allSettled([
				diaasScore ? api.complementFood(foodId, 'diaas') : Promise.reject(),
				pdcaasScore ? api.complementFood(foodId, 'pdcaas') : Promise.reject()
			]);
			if (diaasComp.status === 'fulfilled') diaasComplement = diaasComp.value;
			if (pdcaasComp.status === 'fulfilled') pdcaasComplement = pdcaasComp.value;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>{food ? `${food.name} — Nutri-Matic` : 'Nutri-Matic'}</title>
	{#if food}
		<meta name="description" content="DIAAS/PDCAAS protein quality score and micronutrient profile for {food.name}." />
	{/if}
</svelte:head>

<p><a href="/">&larr; Back</a></p>

{#if loading}
	<p class="muted">Calibrating…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if food}
	<h1>{food.name}</h1>
	<p>{food.protein_g_per_100g} g protein / 100g</p>

	{#if diaasScore}
		<ScoreCard label="DIAAS" score={diaasScore} />
		{#if diaasComplement && diaasComplement.suggestions.length > 0}
			<section class="card complement">
				<h3>Pair with, to improve DIAAS</h3>
				<p class="muted">
					100g {food.name} + 100g of one of these — {diaasComplement.limiting_amino_acid} is what's
					limiting it now.
				</p>
				<ul class="entries">
					{#each diaasComplement.suggestions as s (s.food_id)}
						<li>
							<a href="/foods/{s.food_id}">{s.food_name}</a>
							<span class="muted">
								&rarr; {s.combined_score.toFixed(1)}% (+{s.score_improvement.toFixed(1)})
							</span>
							<p class="why">
								{s.food_name} is rich in {diaasComplement.limiting_amino_acid} — the amino acid
								{food.name}'s protein is shortest on. Combined, one food's surplus covers the
								other's gap, actually simulated and scored (not a folklore guess): DIAAS goes
								from {diaasComplement.original_score.toFixed(1)}% to {s.combined_score.toFixed(1)}%.
							</p>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/if}
	{#if pdcaasScore}
		<ScoreCard label="PDCAAS" score={pdcaasScore} />
		{#if pdcaasComplement && pdcaasComplement.suggestions.length > 0}
			<section class="card complement">
				<h3>Pair with, to improve PDCAAS</h3>
				<p class="muted">
					100g {food.name} + 100g of one of these — {pdcaasComplement.limiting_amino_acid} is what's
					limiting it now.
				</p>
				<ul class="entries">
					{#each pdcaasComplement.suggestions as s (s.food_id)}
						<li>
							<a href="/foods/{s.food_id}">{s.food_name}</a>
							<span class="muted">
								&rarr; {s.combined_score.toFixed(1)}% (+{s.score_improvement.toFixed(1)})
							</span>
							<p class="why">
								{s.food_name} is rich in {pdcaasComplement.limiting_amino_acid} — the amino acid
								{food.name}'s protein is shortest on. Combined, one food's surplus covers the
								other's gap, actually simulated and scored (not a folklore guess): PDCAAS goes
								from {pdcaasComplement.original_score.toFixed(1)}% to {s.combined_score.toFixed(1)}%.
							</p>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/if}

	{#if !diaasScore && !pdcaasScore}
		<p class="alert">No digestibility data on this food — no score can be computed.</p>
	{/if}

	<NutrientBars {nutrients} per="per 100g" />

	{#if provenance}
		<details class="provenance">
			<summary>Show data provenance for this food</summary>
			<dl>
				<dt>Dataset</dt>
				<dd>{provenance.dataset_label ?? 'unknown'}</dd>
				<dt>USDA FDC ID</dt>
				<dd>{provenance.fdc_id ?? 'n/a (manually entered)'}</dd>
				{#if provenance.gtin_upc}
					<dt>Barcode (GTIN/UPC)</dt>
					<dd>{provenance.gtin_upc}</dd>
				{/if}
				{#if provenance.digestibility_diaas_source}
					<dt>DIAAS digestibility</dt>
					<dd>{provenance.digestibility_diaas_source}</dd>
				{/if}
				{#if provenance.digestibility_pdcaas_source}
					<dt>PDCAAS digestibility</dt>
					<dd>{provenance.digestibility_pdcaas_source}</dd>
				{/if}
			</dl>
			<div class="table-scroll">
				<table>
					<thead>
						<tr>
							<th>Nutrient</th>
							<th>USDA nutrient #</th>
							<th>Amount / 100g</th>
						</tr>
					</thead>
					<tbody>
						{#each provenance.nutrients as n (n.key)}
							<tr class:implausible-row={!!n.implausible_reason}>
								<td>{n.name}</td>
								<td>{n.fdc_nutrient_nbr}</td>
								<td>
									{n.amount_per_100g.toLocaleString()}
									{#if n.implausible_reason}
										<span class="implausible-badge" title={n.implausible_reason}>
											⚠ source data error suspected
										</span>
									{/if}
								</td>
							</tr>
							{#if n.implausible_reason}
								<tr class="implausible-row">
									<td colspan="3" class="implausible-explainer">{n.implausible_reason}</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>
		</details>
	{/if}
{/if}

<style>
	.complement {
		margin: var(--space-3) 0 var(--space-5);
	}
	.complement h3 {
		margin-top: 0;
	}
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
	}
	.entries li:last-child {
		border-bottom: none;
	}
	.why {
		margin: 0.15rem 0 var(--space-2);
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}
	.provenance {
		margin: var(--space-4) 0;
		font-size: var(--font-size-sm);
	}
	.provenance dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.2rem var(--space-3);
		margin: var(--space-2) 0 var(--space-4);
	}
	.provenance dt {
		font-weight: var(--font-weight-medium);
		color: var(--color-text-muted);
	}
	.provenance dd {
		margin: 0;
	}
	.provenance table {
		max-width: 40rem;
	}
	.implausible-row {
		background: var(--color-danger-subtle, rgba(220, 38, 38, 0.1));
	}
	.implausible-badge {
		display: inline-block;
		margin-left: var(--space-2);
		font-weight: var(--font-weight-bold);
		color: var(--color-danger);
	}
	.implausible-explainer {
		color: var(--color-danger);
		font-style: italic;
		padding-top: 0;
	}
</style>
