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
			<select bind:value={filter.key}>
				{#each keys as k (k.key)}
					<option value={k.key}>{k.label}</option>
				{/each}
			</select>
			<select bind:value={filter.op}>
				<option value="gte">&ge;</option>
				<option value="lte">&le;</option>
				<option value="eq">=</option>
			</select>
			<input type="number" step="any" bind:value={filter.value} />
			{#if unitFor(filter.key)}
				<span class="unit">{unitFor(filter.key)}</span>
			{/if}
			<button type="button" onclick={() => removeRow(i)}>Remove</button>
		</div>
	{/each}
	<button type="button" onclick={addRow}>+ Add filter</button>
</div>

<style>
	.filter-builder {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.filter-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.filter-row input[type='number'] {
		width: 6rem;
	}
	.unit {
		color: #666;
		font-size: 0.9em;
	}
</style>
