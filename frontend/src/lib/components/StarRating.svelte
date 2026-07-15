<script lang="ts">
	let {
		value,
		onRate,
		onClear
	}: { value: number | null; onRate: (n: number) => void; onClear?: () => void } = $props();

	let hovered: number | null = $state(null);
</script>

<span class="stars">
	{#each [1, 2, 3, 4, 5] as n (n)}
		<button
			type="button"
			class:filled={(hovered ?? value ?? 0) >= n}
			onmouseenter={() => (hovered = n)}
			onmouseleave={() => (hovered = null)}
			onclick={() => onRate(n)}
			aria-label={`Rate ${n} star${n === 1 ? '' : 's'}`}
		>
			★
		</button>
	{/each}
	{#if value !== null && onClear}
		<button type="button" class="clear" onclick={onClear}>Clear</button>
	{/if}
</span>

<style>
	.stars {
		display: inline-flex;
		align-items: center;
		gap: 0.1rem;
	}
	.stars button {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 1.3rem;
		line-height: 1;
		padding: 0.1rem;
		min-width: 2.75rem;
		min-height: 2.75rem;
		color: var(--color-border-strong);
	}
	.stars button.filled {
		color: var(--color-warning);
	}
	.clear {
		font-size: var(--font-size-xs) !important;
		color: var(--color-text-muted) !important;
		margin-left: var(--space-2);
	}
</style>
