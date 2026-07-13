<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { AMINO_ACID_LABELS, type Food, type NutrientAmount, type Score } from '$lib/types';

	const foodId = Number(page.params.id);

	const NUTRIENT_GROUPS: { label: string; keys: string[] }[] = [
		{
			label: 'Fat-soluble vitamins',
			keys: ['vitamin_a', 'retinol', 'beta_carotene', 'vitamin_d', 'vitamin_e', 'vitamin_k1', 'vitamin_k2']
		},
		{
			label: 'Water-soluble vitamins',
			keys: [
				'vitamin_c', 'thiamin', 'riboflavin', 'niacin', 'pantothenic_acid',
				'vitamin_b6', 'biotin', 'folate', 'vitamin_b12', 'choline'
			]
		},
		{
			label: 'Minerals',
			keys: [
				'calcium', 'iron', 'iron_heme', 'iron_non_heme', 'magnesium', 'phosphorus',
				'potassium', 'zinc', 'copper', 'manganese', 'selenium', 'iodine'
			]
		}
	];

	let food: Food | null = $state(null);
	let diaasScore: Score | null = $state(null);
	let pdcaasScore: Score | null = $state(null);
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
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	function groupNutrients(keys: string[]): NutrientAmount[] {
		const byKey = new Map(nutrients.map((n) => [n.key, n]));
		return keys.map((k) => byKey.get(k)).filter((n): n is NutrientAmount => !!n);
	}
</script>

<p><a href="/">&larr; Back</a></p>

{#if loading}
	<p>Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if food}
	<h1>{food.name}</h1>
	<p>{food.protein_g_per_100g} g protein / 100g</p>

	{#each [{ label: 'DIAAS', score: diaasScore }, { label: 'PDCAAS', score: pdcaasScore }] as { label, score } (label)}
		{#if score}
			<section>
				<h2>
						{label}: {score.score.toFixed(1)}%
						{#if score.digestibility_source}
							<span
								class="badge badge-{score.digestibility_source}"
								title={score.digestibility_source === 'estimated'
									? 'Digestibility is a broad food-category estimate, not measured for this specific food'
									: 'Digestibility is a published value for this specific food or a close equivalent'}
								>{score.digestibility_source}</span
							>
						{/if}
					</h2>
				<p class="muted">
					Reference pattern: {score.pattern_used} · Limiting amino acid: <strong
						>{AMINO_ACID_LABELS[score.limiting_amino_acid as keyof typeof AMINO_ACID_LABELS]}</strong
					>
				</p>
				<ul class="bars">
					{#each Object.entries(score.per_aa_ratios) as [aa, ratio] (aa)}
						<li class:limiting={aa === score.limiting_amino_acid}>
							<span class="aa-name">{AMINO_ACID_LABELS[aa as keyof typeof AMINO_ACID_LABELS]}</span>
							<span class="bar-track">
								<span class="bar-fill" style="width: {Math.min(ratio, 150) / 1.5}%"></span>
							</span>
							<span class="aa-value">{ratio.toFixed(0)}%</span>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/each}

	{#if !diaasScore && !pdcaasScore}
		<p>No digestibility data on this food — no score can be computed.</p>
	{/if}

	{#if nutrients.length > 0}
		<h2>Vitamins &amp; minerals <span class="muted">(per 100g)</span></h2>
		{#each NUTRIENT_GROUPS as group (group.label)}
			{@const rows = groupNutrients(group.keys)}
			{#if rows.length > 0}
				<section>
					<h3>{group.label}</h3>
					<ul class="bars">
						{#each rows as n (n.key)}
							<li>
								<span class="aa-name">{n.name}</span>
								<span class="bar-track">
									{#if n.percent_drv_per_100g !== null}
										<span
											class="bar-fill"
											style="width: {Math.min(n.percent_drv_per_100g, 150) / 1.5}%"
										></span>
									{/if}
								</span>
								<span class="aa-value">
									{n.amount_per_100g < 10 ? n.amount_per_100g.toFixed(2) : n.amount_per_100g.toFixed(0)}
									{n.unit}
									{#if n.percent_drv_per_100g !== null}
										<span class="muted">({n.percent_drv_per_100g.toFixed(0)}% DRV)</span>
									{/if}
								</span>
							</li>
						{/each}
					</ul>
				</section>
			{/if}
		{/each}
		<p class="muted">
			% DRV is against a single generic-adult reference value, not adjusted for your age, sex,
			or life stage.
		</p>
	{/if}
{/if}

<style>
	.error {
		color: #b00020;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.badge {
		display: inline-block;
		font-size: 0.6em;
		font-weight: normal;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		padding: 0.15em 0.5em;
		border-radius: 999px;
		vertical-align: middle;
		margin-left: 0.4em;
	}
	.badge-measured {
		background: #dff0d8;
		color: #2d6a2d;
	}
	.badge-estimated {
		background: #fdf3d0;
		color: #8a6d00;
	}
	.bars {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.bars li {
		display: grid;
		grid-template-columns: 12rem 1fr auto;
		align-items: center;
		gap: 0.5rem;
	}
	.bars .aa-value {
		white-space: nowrap;
	}
	.bars li.limiting .aa-name,
	.bars li.limiting .aa-value {
		font-weight: bold;
		color: #b00020;
	}
	.bar-track {
		background: #eee;
		border-radius: 4px;
		height: 0.75rem;
		overflow: hidden;
	}
	.bar-fill {
		display: block;
		height: 100%;
		background: #3a7d44;
	}
	.limiting .bar-fill {
		background: #b00020;
	}
</style>
