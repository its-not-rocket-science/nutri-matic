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
				is_lactating: isLactating
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
	<p>Loading…</p>
{:else}
	<form onsubmit={handleSubmit}>
		<label>
			Sex
			<select bind:value={sex}>
				<option value={null}>Not set</option>
				<option value="female">Female</option>
				<option value="male">Male</option>
			</select>
		</label>

		<label>
			Birth year
			<input type="number" min="1900" max="2026" bind:value={birthYear} />
		</label>

		<label>
			Activity level
			<select bind:value={activityLevel}>
				<option value={null}>Not set</option>
				<option value="sedentary">Sedentary</option>
				<option value="light">Lightly active</option>
				<option value="moderate">Moderately active</option>
				<option value="active">Active</option>
				<option value="very_active">Very active</option>
			</select>
		</label>

		<label class="checkbox">
			<input type="checkbox" bind:checked={isPregnant} />
			Pregnant
		</label>
		<label class="checkbox">
			<input type="checkbox" bind:checked={isLactating} />
			Lactating
		</label>

		<p class="muted">
			Sex and pregnancy/lactation status are used to select the right reference values when
			checking your diary against nutrient targets. Activity level is stored but not yet used
			(it would feed energy/calorie targets, which this app doesn't track yet).
		</p>

		{#if error}
			<p class="error">{error}</p>
		{/if}
		{#if saved}
			<p class="success">Saved.</p>
		{/if}

		<button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>
	</form>
{/if}

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 24rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	label.checkbox {
		flex-direction: row;
		align-items: center;
		gap: 0.5rem;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	.error {
		color: #b00020;
	}
	.success {
		color: #2d6a2d;
	}
</style>
