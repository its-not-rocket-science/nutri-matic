<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { WeightLog } from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	function defaultRange(): { start: string; end: string } {
		const end = new Date();
		const start = new Date();
		start.setUTCDate(start.getUTCDate() - 90);
		return { start: toIsoDate(start), end: toIsoDate(end) };
	}

	let startDate = $state(defaultRange().start);
	let endDate = $state(defaultRange().end);
	let logs: WeightLog[] = $state([]);
	let error: string | null = $state(null);
	let loading = $state(true);

	let logDate = $state(toIsoDate(new Date()));
	let weightKg = $state<number | null>(null);
	let saving = $state(false);
	let deletingId: number | null = $state(null);

	async function load() {
		loading = true;
		error = null;
		try {
			logs = await api.listWeightLogs(startDate, endDate);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		await load();
	});

	async function handleLog(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		if (weightKg === null || weightKg <= 0) {
			error = 'Enter a positive weight.';
			return;
		}
		saving = true;
		try {
			await api.logWeight({ log_date: logDate, weight_kg: weightKg });
			weightKg = null;
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}

	async function handleDelete(id: number) {
		error = null;
		deletingId = id;
		try {
			await api.deleteWeightLog(id);
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			deletingId = null;
		}
	}

	const CHART_WIDTH = 400;
	const CHART_HEIGHT = 160;
	const PADDING = 24;

	const chartPoints = $derived.by(() => {
		if (logs.length === 0) return [];
		const weights = logs.map((l) => l.weight_kg);
		const minWeight = Math.min(...weights);
		const maxWeight = Math.max(...weights);
		const range = maxWeight - minWeight || 1;
		const dates = logs.map((l) => new Date(l.log_date + 'T00:00:00Z').getTime());
		const minDate = Math.min(...dates);
		const maxDate = Math.max(...dates);
		const dateRange = maxDate - minDate || 1;

		return logs.map((l) => {
			const t = new Date(l.log_date + 'T00:00:00Z').getTime();
			const x = PADDING + ((t - minDate) / dateRange) * (CHART_WIDTH - 2 * PADDING);
			const y =
				CHART_HEIGHT -
				PADDING -
				((l.weight_kg - minWeight) / range) * (CHART_HEIGHT - 2 * PADDING);
			return { x, y, log: l };
		});
	});

	const polylinePoints = $derived(chartPoints.map((p) => `${p.x},${p.y}`).join(' '));
</script>

<h1>Weight log</h1>
<p><a href="/">&larr; Back</a></p>

{#if error}
	<p class="error">{error}</p>
{/if}

<form class="card log-form" onsubmit={handleLog}>
	<h3>Log weight</h3>
	<div class="field">
		<label for="log-date">Date</label>
		<input id="log-date" type="date" bind:value={logDate} required />
	</div>
	<div class="field">
		<label for="log-weight">Weight (kg)</label>
		<input id="log-weight" type="number" step="any" min="0" bind:value={weightKg} required />
	</div>
	<button type="submit" class="btn btn-primary" disabled={saving}>
		{saving ? 'Saving…' : 'Log weight'}
	</button>
</form>

<div class="controls">
	<div class="field">
		<label for="range-start">From</label>
		<input id="range-start" type="date" bind:value={startDate} onchange={load} />
	</div>
	<div class="field">
		<label for="range-end">To</label>
		<input id="range-end" type="date" bind:value={endDate} onchange={load} />
	</div>
</div>

{#if loading}
	<p class="muted">Loading…</p>
{:else if logs.length === 0}
	<p class="muted">No weight logged in this range yet.</p>
{:else}
	<div class="card chart-card">
		<svg class="chart" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" aria-label="Weight over time">
			<polyline points={polylinePoints} class="line" />
			{#each chartPoints as p (p.log.id)}
				<circle cx={p.x} cy={p.y} r="3" class="point" />
			{/each}
		</svg>
	</div>

	<ul class="entries">
		{#each [...logs].reverse() as log (log.id)}
			<li>
				<span>{log.log_date}</span>
				<span class="muted">{log.weight_kg}kg</span>
				<button
					type="button"
					class="btn btn-danger"
					onclick={() => handleDelete(log.id)}
					disabled={deletingId === log.id}
				>
					{deletingId === log.id ? 'Deleting…' : 'Delete'}
				</button>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.log-form {
		max-width: 20rem;
		margin: var(--space-5) 0;
	}
	.controls {
		display: flex;
		gap: var(--space-4);
		margin-bottom: var(--space-4);
	}
	.chart-card {
		max-width: 30rem;
		margin-bottom: var(--space-4);
	}
	.chart {
		width: 100%;
		height: auto;
		display: block;
	}
	.line {
		fill: none;
		stroke: var(--color-primary);
		stroke-width: 2;
	}
	.point {
		fill: var(--color-primary);
	}
	.entries {
		list-style: none;
		padding: 0;
	}
	.entries li {
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.entries li:last-child {
		border-bottom: none;
	}
</style>
