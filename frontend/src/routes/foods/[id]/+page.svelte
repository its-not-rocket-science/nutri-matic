<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import NutrientBars from '$lib/components/NutrientBars.svelte';
	import ScoreCard from '$lib/components/ScoreCard.svelte';
	import type { Complement, Food, NutrientAmount, Score } from '$lib/types';

	const foodId = Number(page.params.id);

	let food: Food | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
	let diaasComplement: Complement | null = $state(null);
	let pdcaasComplement: Complement | null = $state(null);
	let nutrients: NutrientAmount[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			food = await api.getFood(foodId);
			const [diaas, pdcaas, nutrientResult] = await Promise.allSettled([
				food.digestibility_diaas ? api.scoreFood(foodId, 'diaas') : Promise.reject(),
				food.digestibility_pdcaas !== null ? api.scoreFood(foodId, 'pdcaas') : Promise.reject(),
				api.getNutrients(foodId)
			]);
			if (diaas.status === 'fulfilled') diaasScore = diaas.value;
			if (pdcaas.status === 'fulfilled') pdcaasScore = pdcaas.value;
			if (nutrientResult.status === 'fulfilled') nutrients = nutrientResult.value;

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

<p><a href="/">&larr; Back</a></p>

{#if loading}
	<p>Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if food}
	<h1>{food.name}</h1>
	<p>{food.protein_g_per_100g} g protein / 100g</p>

	{#if diaasScore}
		<ScoreCard label="DIAAS" score={diaasScore} />
		{#if diaasComplement && diaasComplement.suggestions.length > 0}
			<section class="complement">
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
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/if}
	{#if pdcaasScore}
		<ScoreCard label="PDCAAS" score={pdcaasScore} />
		{#if pdcaasComplement && pdcaasComplement.suggestions.length > 0}
			<section class="complement">
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
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/if}

	{#if !diaasScore && !pdcaasScore}
		<p>No digestibility data on this food — no score can be computed.</p>
	{/if}

	<NutrientBars {nutrients} per="per 100g" />
{/if}

<style>
	.error {
		color: #b00020;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.complement {
		margin: 0.5rem 0 1.5rem;
		padding: 0.75rem 1rem;
		border: 1px solid #eee;
		border-radius: 4px;
	}
	.complement h3 {
		margin-top: 0;
	}
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: 0.2rem 0;
	}
</style>
