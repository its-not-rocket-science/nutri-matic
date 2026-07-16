<script lang="ts">
	import type { FilterKey, NutrientFilterInput } from '$lib/types';

	let { keys, filters = $bindable([]) }: { keys: FilterKey[]; filters: NutrientFilterInput[] } =
		$props();

	function addRow() {
		if (keys.length === 0) return;
		filters = [...filters, { key: keys[0].key, op: 'gte', value: 0 }];
	}

	function removeRow(index: number) {
		filters = filters.filter((_, i) => i !== index);
	}

	function unitFor(key: string): string | null {
		return keys.find((k) => k.key === key)?.unit ?? null;
	}
</script>

<div class="filter-builder">
	{#each filters as filter, i (i)}
		<div class="filter-row">
			<select bind:value={filter.key} aria-label="Nutrient">
				{#each keys as k (k.key)}
					<option value={k.key}>{k.label}</option>
				{/each}
			</select>
			<select bind:value={filter.op} aria-label="Comparison">
				<option value="gte">&ge;</option>
				<option value="lte">&le;</option>
				<option value="eq">=</option>
			</select>
			<input type="number" step="any" bind:value={filter.value} aria-label="Value" />
			{#if unitFor(filter.key)}
				<span class="unit">{unitFor(filter.key)}</span>
			{/if}
			<button type="button" class="btn btn-danger" onclick={() => removeRow(i)}>Remove</button>
		</div>
	{/each}
	<button type="button" class="btn btn-secondary" onclick={addRow}>+ Add filter</button>
</div>

<style>
	.filter-builder {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.filter-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.filter-row select,
	.filter-row input {
		width: auto;
	}
	.filter-row input[type='number'] {
		width: 6rem;
	}
	.unit {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}
</style>
