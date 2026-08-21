<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import type { Complement, Food, FoodProvenance, NutrientAmount, Phytate, Score } from '$lib/types';

	const foodId = Number(page.params.id);

	let food: Food | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let diaasUnavailableReason: string | null = $state(null);
	let pdcaasUnavailableReason: string | null = $state(null);
	let diaasComplement: Complement | null = $state(null);
	let pdcaasComplement: Complement | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	let provenance: FoodProvenance | null = $state(null);
	let phytate: Phytate | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			food = await api.getFood(foodId);
			const [diaas, pdcaas, nutrientResult, provenanceResult, phytateResult] = await Promise.allSettled([
				food.digestibility_diaas
					? api.scoreFood(foodId, 'diaas')
					: Promise.reject(new Error('No DIAAS digestibility data for this food.')),
				food.digestibility_pdcaas !== null
					? api.scoreFood(foodId, 'pdcaas')
					: Promise.reject(new Error('No PDCAAS digestibility data for this food.')),
				api.getNutrients(foodId),
				api.getFoodProvenance(foodId),
				api.getPhytate(foodId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			else diaasUnavailableReason = diaas.reason instanceof Error ? diaas.reason.message : String(diaas.reason);
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			else pdcaasUnavailableReason = pdcaas.reason instanceof Error ? pdcaas.reason.message : String(pdcaas.reason);
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;
			if (provenanceResult.status === 'fulfilled') provenance = provenanceResult.value;
			if (phytateResult.status === 'fulfilled') phytate = phytateResult.value;

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
	{:else if diaasUnavailableReason}
		<p class="alert">DIAAS score unavailable: {diaasUnavailableReason}</p>
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
	{:else if pdcaasUnavailableReason}
		<p class="alert">PDCAAS score unavailable: {pdcaasUnavailableReason}</p>
	{/if}

	<NutrientBars {nutrients} per="per 100g" />

	{#if phytate && phytate.status === 'selected' && phytate.observations.length > 0}
		<section class="card phytate">
			<h3>Phytate</h3>
			<p class="muted">
				Phytate (phytic acid) can reduce how much iron, zinc, and calcium the body absorbs from a
				meal — but it also occurs naturally in many nutritious whole grains, legumes, nuts, and
				seeds, and isn't simply a toxin to avoid. Molar ratios (phytate:zinc, phytate:iron) are
				contextual indicators of a meal's likely bioavailability, not predictions of any one
				person's actual absorption.
			</p>
			{#if phytate.truncated}
				<p class="muted">Showing a subset of the observations available for this food.</p>
			{/if}
			<ul class="entries">
				{#each phytate.observations as o (o.compound_fraction)}
					<li>
						<strong>{o.compound_fraction}</strong> ({o.family.replace('_', ' ')}):
						{o.value.toLocaleString()} {o.unit} / {o.basis.replace(/_/g, ' ')}
						{#if o.is_estimate}
							<span class="estimate-badge" title="Matched by category/analogue, not a source-verified identity match">
								estimate
							</span>
						{/if}
						{#if o.preparation_compatible === false}
							<span class="estimate-badge" title="This observation's stated preparation doesn't match what you asked about">
								preparation mismatch
							</span>
						{/if}
						<p class="why">
							{o.explanation}
							{#if o.analytical_method}— method: {o.analytical_method}{/if}
						</p>
					</li>
				{/each}
			</ul>
			<p class="muted">
				Source: {phytate.observations[0].source_dataset_citation}. See the
				<a href="/methodology#phytate">full methodology</a> for coverage limitations and how these
				values are selected.
			</p>
		</section>
	{:else if phytate && phytate.status === 'insufficient_data'}
		<section class="card phytate">
			<h3>Phytate</h3>
			<p class="muted">{phytate.explanation}</p>
		</section>
	{/if}

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
	.phytate {
		margin: var(--space-3) 0 var(--space-5);
	}
	.phytate h3 {
		margin-top: 0;
	}
	.estimate-badge {
		display: inline-block;
		margin-left: var(--space-2);
		padding: 0.05rem 0.4rem;
		font-size: var(--font-size-sm);
		border-radius: var(--radius-sm);
		background: var(--color-bg-subtle, rgba(120, 120, 120, 0.15));
		color: var(--color-text-muted);
	}
</style>
