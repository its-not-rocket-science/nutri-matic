<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { User } from '$lib/types';

	let sex: User['sex'] = $state(null);
	let birthYear: number | null = $state(null);
	let activityLevel: User['activity_level'] = $state(null);
	let isPregnant = $state(false);
	let isLactating = $state(false);
	let weightKg: number | null = $state(null);
	let heightCm: number | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);
	let saved = $state(false);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			const profile = await api.getProfile();
			sex = profile.sex;
			birthYear = profile.birth_year;
			activityLevel = profile.activity_level;
			isPregnant = profile.is_pregnant;
			isLactating = profile.is_lactating;
			weightKg = profile.weight_kg;
			heightCm = profile.height_cm;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = null;
		saved = false;
		saving = true;
		try {
			const updated = await api.updateProfile({
				sex,
				birth_year: birthYear,
				activity_level: activityLevel,
				is_pregnant: isPregnant,
				is_lactating: isLactating,
				weight_kg: weightKg,
				height_cm: heightCm
			});
			auth.setUser(updated);
			saved = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}
</script>

<h1>Profile</h1>
<p><a href="/">&larr; Back</a></p>

{#if loading}
	<p class="muted">Loading…</p>
{:else}
	<form class="card profile-form" onsubmit={handleSubmit}>
		<div class="field">
			<label for="sex">Sex</label>
			<select id="sex" bind:value={sex}>
				<option value={null}>Not set</option>
				<option value="female">Female</option>
				<option value="male">Male</option>
			</select>
		</div>

		<div class="field">
			<label for="birth-year">Birth year</label>
			<input id="birth-year" type="number" min="1900" max="2026" bind:value={birthYear} />
		</div>

		<div class="field">
			<label for="activity-level">Activity level</label>
			<select id="activity-level" bind:value={activityLevel}>
				<option value={null}>Not set</option>
				<option value="sedentary">Sedentary</option>
				<option value="light">Lightly active</option>
				<option value="moderate">Moderately active</option>
				<option value="active">Active</option>
				<option value="very_active">Very active</option>
			</select>
		</div>

		<label class="checkbox field">
			<input type="checkbox" bind:checked={isPregnant} />
			Pregnant
		</label>
		<label class="checkbox field">
			<input type="checkbox" bind:checked={isLactating} />
			Lactating
		</label>

		<div class="field">
			<label for="weight">Weight (kg)</label>
			<input id="weight" type="number" step="any" min="0" bind:value={weightKg} />
		</div>
		<div class="field">
			<label for="height">Height (cm)</label>
			<input id="height" type="number" step="any" min="0" bind:value={heightCm} />
		</div>

		<p class="muted">
			Sex and pregnancy/lactation status are used to select the right reference values when
			checking your diary against nutrient targets. Weight, height, sex, birth year, and activity
			level together are used to calculate your daily calorie target (Mifflin-St Jeor) — all five
			are needed for that; anything missing just means no calorie target shows up.
		</p>

		{#if error}
			<p class="error">{error}</p>
		{/if}
		{#if saved}
			<p class="success-text">Saved.</p>
		{/if}

		<button type="submit" class="btn btn-primary" disabled={saving}>
			{saving ? 'Saving…' : 'Save profile'}
		</button>
	</form>
{/if}

<style>
	.profile-form {
		max-width: 28rem;
	}
	.checkbox {
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: var(--space-2);
	}
</style>
