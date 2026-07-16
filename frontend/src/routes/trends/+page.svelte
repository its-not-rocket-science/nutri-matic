<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import PrintButton from '$lib/components/PrintButton.svelte';
	import { downloadCsv } from '$lib/csv';
	import type { DiaryTrends, TrendGroupBy } from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	function defaultRange(groupBy: TrendGroupBy): { start: string; end: string } {
		const end = new Date();
		const start = new Date();
		if (groupBy === 'week') {
			start.setUTCDate(start.getUTCDate() - 7 * 8); // last 8 weeks
		} else {
			start.setUTCMonth(start.getUTCMonth() - 6); // last 6 months
		}
		return { start: toIsoDate(start), end: toIsoDate(end) };
	}

	let groupBy: TrendGroupBy = $state('week');
	let startDate = $state(defaultRange('week').start);
	let endDate = $state(defaultRange('week').end);
	let trends: DiaryTrends | null = $state(null);
	let selectedKey: string | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);

	const nutrientOptions = $derived.by(() => {
		if (!trends) return [];
		const byKey = new Map<string, string>();
		for (const bucket of trends.buckets) {
			for (const n of bucket.nutrients) byKey.set(n.key, n.name);
		}
		return [...byKey.entries()].sort((a, b) => a[1].localeCompare(b[1]));
	});

	const chartData = $derived.by(() => {
		if (!trends || !selectedKey) return [];
		return trends.buckets.map((bucket) => ({
			bucket,
			nutrient: bucket.nutrients.find((n) => n.key === selectedKey) ?? null
		}));
	});

	function bucketLabel(bucketStart: string): string {
		const d = new Date(bucketStart + 'T00:00:00Z');
		return groupBy === 'week'
			? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })
			: d.toLocaleDateString(undefined, { month: 'short', year: 'numeric', timeZone: 'UTC' });
	}

	async function load() {
		loading = true;
		error = null;
		try {
			trends = await api.getDiaryTrends(startDate, endDate, groupBy);
			if (!selectedKey && nutrientOptions.length > 0) selectedKey = nutrientOptions[0][0];
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function handleGroupByChange(newGroupBy: TrendGroupBy) {
		groupBy = newGroupBy;
		const range = defaultRange(newGroupBy);
		startDate = range.start;
		endDate = range.end;
		load();
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		await load();
	});

	const CHART_HEIGHT = 160;
	const BAR_WIDTH = 36;
	const GAP = 20;
	const DISPLAY_CEILING = 200; // %DRV bars taller than this are capped visually; the real value is still labelled

	function barHeight(percent: number): number {
		return (Math.min(percent, DISPLAY_CEILING) / DISPLAY_CEILING) * CHART_HEIGHT;
	}

	function handleDownloadCsv() {
		if (!trends) return;
		const rows: (string | number | null)[][] = [
			['Bucket start', 'Bucket end', 'Logged days', 'Nutrient', 'Avg amount', 'Unit', 'DRV', 'Avg % DRV']
		];
		for (const bucket of trends.buckets) {
			for (const n of bucket.nutrients) {
				rows.push([
					bucket.bucket_start,
					bucket.bucket_end,
					bucket.logged_days,
					n.name,
					n.avg_amount,
					n.unit,
					n.adult_drv,
					n.avg_percent_drv
				]);
			}
		}
		downloadCsv(`diet-trends-${groupBy}-${startDate}-to-${endDate}.csv`, rows);
	}
</script>

<h1>Diet trends</h1>
<p class="no-print"><a href="/">&larr; Back</a></p>

<div class="controls no-print">
	<div class="toggle">
		<button type="button" class:active={groupBy === 'week'} onclick={() => handleGroupByChange('week')}>
			Week
		</button>
		<button type="button" class:active={groupBy === 'month'} onclick={() => handleGroupByChange('month')}>
			Month
		</button>
	</div>

	<label>
		From
		<input type="date" bind:value={startDate} onchange={load} />
	</label>
	<label>
		To
		<input type="date" bind:value={endDate} onchange={load} />
	</label>
</div>

<p class="range-heading">{groupBy === 'week' ? 'Weekly' : 'Monthly'} trends, {startDate} to {endDate}</p>

{#if error}
	<p class="error">{error}</p>
{/if}

{#if loading}
	<p class="muted">Calibrating…</p>
{:else if !trends || trends.buckets.length === 0}
	<p class="muted">Nothing logged in this range yet — <a href="/diary">log a few days in the diary</a> to see trends here.</p>
{:else}
	<div class="export-actions no-print">
		<PrintButton />
		<button type="button" onclick={handleDownloadCsv}>Download CSV (all nutrients)</button>
	</div>

	<label class="nutrient-picker no-print">
		Nutrient
		<select bind:value={selectedKey}>
			{#each nutrientOptions as [key, name] (key)}
				<option value={key}>{name}</option>
			{/each}
		</select>
	</label>

	{#if selectedKey}
		<p class="selected-nutrient-heading">
			{nutrientOptions.find(([key]) => key === selectedKey)?.[1]}
		</p>
	{/if}

	{#if selectedKey}
		{@const hasDrv = chartData.some((d) => d.nutrient?.adult_drv)}
		<svg
			class="chart"
			viewBox="0 0 {chartData.length * (BAR_WIDTH + GAP) + GAP} {CHART_HEIGHT + 50}"
			role="img"
			aria-label="Nutrient trend chart"
		>
			{#if hasDrv}
				{@const referenceY = CHART_HEIGHT - barHeight(100) + 20}
				<line
					x1="0"
					y1={referenceY}
					x2={chartData.length * (BAR_WIDTH + GAP) + GAP}
					y2={referenceY}
					class="reference-line"
				/>
				<text x="4" y={referenceY - 4} class="reference-label">100% DRV</text>
			{/if}

			{#each chartData as { bucket, nutrient }, i (bucket.bucket_start)}
				{@const x = GAP + i * (BAR_WIDTH + GAP)}
				{@const value = nutrient?.avg_percent_drv ?? nutrient?.avg_amount ?? 0}
				{@const height = nutrient ? barHeight(nutrient.avg_percent_drv ?? 0) : 0}
				{@const y = CHART_HEIGHT + 20 - height}
				<g>
					{#if nutrient}
						<rect {x} {y} width={BAR_WIDTH} {height} class="bar" />
						<text x={x + BAR_WIDTH / 2} y={y - 4} class="value-label" text-anchor="middle">
							{nutrient.avg_percent_drv !== null
								? `${Math.round(nutrient.avg_percent_drv)}%`
								: `${value.toFixed(1)}${nutrient.unit}`}
						</text>
					{/if}
					<text x={x + BAR_WIDTH / 2} y={CHART_HEIGHT + 38} class="bucket-label" text-anchor="middle">
						{bucketLabel(bucket.bucket_start)}
					</text>
					<text x={x + BAR_WIDTH / 2} y={CHART_HEIGHT + 50} class="logged-days-label" text-anchor="middle">
						{bucket.logged_days}d logged
					</text>
				</g>
			{/each}
		</svg>
	{/if}
{/if}

<style>
	.controls {
		display: flex;
		align-items: flex-end;
		gap: 1rem;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}
	.toggle {
		display: flex;
		gap: 0.25rem;
	}
	.toggle button.active {
		font-weight: 600;
		text-decoration: underline;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.9em;
	}
	.nutrient-picker {
		max-width: 20rem;
		margin-bottom: 1rem;
	}
	.error {
		color: var(--color-danger);
	}
	.muted {
		color: var(--color-text-muted);
		font-size: 0.9em;
	}
	.chart {
		width: 100%;
		max-width: 40rem;
		height: auto;
	}
	.bar {
		fill: var(--color-primary);
	}
	.reference-line {
		stroke: var(--color-danger);
		stroke-width: 1;
		stroke-dasharray: 4 3;
	}
	.reference-label {
		font-size: 7px;
		fill: var(--color-danger);
	}
	.value-label {
		font-size: 8px;
		fill: var(--color-text);
	}
	.bucket-label {
		font-size: 8px;
		fill: var(--color-text-muted);
	}
	.logged-days-label {
		font-size: 7px;
		fill: var(--color-text-subtle);
	}
	.range-heading,
	.selected-nutrient-heading {
		display: none;
	}
	.export-actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}
	@media print {
		.no-print {
			display: none !important;
		}
		.range-heading {
			display: block;
			font-weight: 600;
		}
		.selected-nutrient-heading {
			display: block;
			font-weight: 600;
			margin-top: 1rem;
		}
	}
</style>
