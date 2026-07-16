<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { DietaryConstraint, DietaryVocabulary, User } from '$lib/types';

	let sex: User['sex'] = $state(null);
	let birthYear: number | null = $state(null);
	let activityLevel: User['activity_level'] = $state(null);
	let isPregnant = $state(false);
	let isLactating = $state(false);
	let weightKg: number | null = $state(null);
	let heightCm: number | null = $state(null);
	let dietaryPattern: string | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);
	let saved = $state(false);

	let vocabulary: DietaryVocabulary | null = $state(null);
	let constraints: DietaryConstraint[] = $state([]);
	let constraintsError: string | null = $state(null);

	const allergies = $derived(constraints.filter((c) => c.category === 'allergy' || c.category === 'intolerance'));
	const religious = $derived(constraints.filter((c) => c.category === 'religious'));
	const medical = $derived(constraints.filter((c) => c.category === 'medical'));
	const preferences = $derived(constraints.filter((c) => c.category === 'preference'));

	function tagLabel(tag: string | null): string {
		if (!tag || !vocabulary) return tag ?? '';
		return (
			vocabulary.allergen_tags.find((t) => t.key === tag)?.label ??
			vocabulary.religious_requirements.find((t) => t.key === tag)?.label ??
			tag
		);
	}

	// Allergy/intolerance form state
	let newAllergyTag = $state('');
	let newAllergyCategory: 'allergy' | 'intolerance' = $state('allergy');
	let newAllergySeverity: 'hard_exclude' | 'avoid' = $state('hard_exclude');
	let addingAllergy = $state(false);

	// Religious requirement form state
	let newReligiousTag = $state('');
	let addingReligious = $state(false);

	// Medical / preference free-text form state
	let newMedicalNote = $state('');
	let addingMedical = $state(false);
	let newPreferenceNote = $state('');
	let addingPreference = $state(false);

	async function loadConstraints() {
		constraintsError = null;
		try {
			constraints = await api.listDietaryConstraints();
		} catch (e) {
			constraintsError = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		try {
			const [profile, vocab] = await Promise.all([api.getProfile(), api.getDietaryVocabulary()]);
			sex = profile.sex;
			birthYear = profile.birth_year;
			activityLevel = profile.activity_level;
			isPregnant = profile.is_pregnant;
			isLactating = profile.is_lactating;
			weightKg = profile.weight_kg;
			heightCm = profile.height_cm;
			dietaryPattern = profile.dietary_pattern;
			vocabulary = vocab;
			await loadConstraints();
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
				height_cm: heightCm,
				dietary_pattern: dietaryPattern
			});
			auth.setUser(updated);
			saved = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}

	async function addAllergy(e: SubmitEvent) {
		e.preventDefault();
		if (!newAllergyTag) return;
		addingAllergy = true;
		constraintsError = null;
		try {
			await api.createDietaryConstraint({
				category: newAllergyCategory,
				tag: newAllergyTag,
				severity: newAllergySeverity,
				note: null
			});
			newAllergyTag = '';
			await loadConstraints();
		} catch (e) {
			constraintsError = e instanceof Error ? e.message : String(e);
		} finally {
			addingAllergy = false;
		}
	}

	async function addReligious(e: SubmitEvent) {
		e.preventDefault();
		if (!newReligiousTag) return;
		addingReligious = true;
		constraintsError = null;
		try {
			await api.createDietaryConstraint({
				category: 'religious',
				tag: newReligiousTag,
				severity: 'hard_exclude',
				note: null
			});
			newReligiousTag = '';
			await loadConstraints();
		} catch (e) {
			constraintsError = e instanceof Error ? e.message : String(e);
		} finally {
			addingReligious = false;
		}
	}

	async function addMedical(e: SubmitEvent) {
		e.preventDefault();
		if (!newMedicalNote.trim()) return;
		addingMedical = true;
		constraintsError = null;
		try {
			await api.createDietaryConstraint({ category: 'medical', tag: null, severity: null, note: newMedicalNote });
			newMedicalNote = '';
			await loadConstraints();
		} catch (e) {
			constraintsError = e instanceof Error ? e.message : String(e);
		} finally {
			addingMedical = false;
		}
	}

	async function addPreference(e: SubmitEvent) {
		e.preventDefault();
		if (!newPreferenceNote.trim()) return;
		addingPreference = true;
		constraintsError = null;
		try {
			await api.createDietaryConstraint({
				category: 'preference',
				tag: null,
				severity: null,
				note: newPreferenceNote
			});
			newPreferenceNote = '';
			await loadConstraints();
		} catch (e) {
			constraintsError = e instanceof Error ? e.message : String(e);
		} finally {
			addingPreference = false;
		}
	}

	async function removeConstraint(id: number) {
		constraintsError = null;
		try {
			await api.deleteDietaryConstraint(id);
			await loadConstraints();
		} catch (e) {
			constraintsError = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<h1>Profile</h1>
<p><a href="/">&larr; Back</a></p>

{#if loading}
	<p class="muted">Calibrating…</p>
{:else}
	<form class="card profile-form" onsubmit={handleSubmit}>
		<h2>Personal details</h2>
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

		{#if vocabulary}
			<div class="field">
				<label for="dietary-pattern">Dietary pattern</label>
				<select id="dietary-pattern" bind:value={dietaryPattern}>
					<option value={null}>Not set</option>
					{#each vocabulary.dietary_patterns as p (p.key)}
						<option value={p.key}>{p.label}</option>
					{/each}
				</select>
				<p class="muted field-note">
					Why this exists: your pattern is applied as a hard exclusion everywhere foods are
					suggested — search, recipes, meal planning, the optimiser — so a vegan profile never
					gets shown meat, dairy, or egg. It's checked against each food's name (see the
					allergies section below for why that's not the same as a verified ingredient list).
				</p>
			</div>
		{/if}

		{#if error}
			<p class="error">{error}</p>
		{/if}
		{#if saved}
			<p class="success-text">Saved. The instrument has updated its records.</p>
		{/if}

		<button type="submit" class="btn btn-primary" disabled={saving}>
			{saving ? 'Saving…' : 'Save profile'}
		</button>
	</form>

	{#if constraintsError}
		<p class="error">{constraintsError}</p>
	{/if}

	<section class="card constraint-section">
		<h2>Allergies &amp; intolerances</h2>
		<p class="muted field-note">
			Why this exists: an allergy is checked as a <strong>hard exclusion</strong> — matching foods
			are removed from search, recipe, and meal-plan results outright, not just flagged. An
			intolerance defaults the same way, but you can mark it "avoid" instead if you'd rather see
			it flagged than hidden. <strong>Important:</strong> this is a name-based match against USDA's
			food descriptions, not a verified ingredients list — reliable for plain ingredients ("Milk,
			whole"), much less so for packaged products, where the product name often doesn't mention
			every allergen. Always check the actual label. This app cannot replace that.
		</p>
		{#if allergies.length > 0}
			<ul class="constraint-list">
				{#each allergies as c (c.id)}
					<li>
						<span>
							{tagLabel(c.tag)}
							<span class="badge {c.severity === 'hard_exclude' ? 'badge-limiting' : 'badge-estimated'}">
								{c.severity === 'hard_exclude' ? 'excluded' : 'avoid'}
							</span>
							<span class="muted">({c.category})</span>
						</span>
						<button type="button" class="btn btn-danger" onclick={() => removeConstraint(c.id)}>Remove</button>
					</li>
				{/each}
			</ul>
		{/if}
		{#if vocabulary}
			<form class="inline-form" onsubmit={addAllergy}>
				<select bind:value={newAllergyCategory} aria-label="Category">
					<option value="allergy">Allergy</option>
					<option value="intolerance">Intolerance</option>
				</select>
				<select bind:value={newAllergyTag} aria-label="Ingredient">
					<option value="">Choose an ingredient…</option>
					{#each vocabulary.allergen_tags as t (t.key)}
						<option value={t.key}>{t.label}</option>
					{/each}
				</select>
				<select bind:value={newAllergySeverity} aria-label="Severity">
					<option value="hard_exclude">Hard exclude</option>
					<option value="avoid">Avoid (flag only)</option>
				</select>
				<button type="submit" class="btn btn-secondary" disabled={addingAllergy || !newAllergyTag}>
					{addingAllergy ? 'Adding…' : 'Add'}
				</button>
			</form>
		{/if}
	</section>

	<section class="card constraint-section">
		<h2>Religious requirements</h2>
		<p class="muted field-note">
			Why this exists: applied as a hard exclusion, the same as allergies. Real religious dietary
			law involves more than ingredient exclusion — halal and kosher both require a specific
			slaughter method, kosher requires meat/dairy separation, and Jain practice excludes root
			vegetables — none of which can be checked from a food's name. This only enforces the
			ingredient-level subset that's actually checkable; treat it as a starting filter, not a
			certification.
		</p>
		{#if religious.length > 0}
			<ul class="constraint-list">
				{#each religious as c (c.id)}
					<li>
						<span>{tagLabel(c.tag)} <span class="badge badge-limiting">excluded</span></span>
						<button type="button" class="btn btn-danger" onclick={() => removeConstraint(c.id)}>Remove</button>
					</li>
				{/each}
			</ul>
		{/if}
		{#if vocabulary}
			<form class="inline-form" onsubmit={addReligious}>
				<select bind:value={newReligiousTag} aria-label="Requirement">
					<option value="">Choose a requirement…</option>
					{#each vocabulary.religious_requirements as p (p.key)}
						<option value={p.key}>{p.label}</option>
					{/each}
				</select>
				<button type="submit" class="btn btn-secondary" disabled={addingReligious || !newReligiousTag}>
					{addingReligious ? 'Adding…' : 'Add'}
				</button>
			</form>
		{/if}
	</section>

	<section class="card constraint-section">
		<h2>Medical considerations</h2>
		<p class="muted field-note">
			Why this exists: purely for your own reference — shown back to you here, never used to
			filter or exclude anything automatically. A condition like "diabetes" or "kidney disease"
			implies dietary rules too individual and clinically-specific for this app to enforce safely;
			guessing would be worse than not trying. If a condition needs a real dietary restriction,
			add it as an allergy/intolerance above using whichever ingredient it actually maps to.
		</p>
		{#if medical.length > 0}
			<ul class="constraint-list">
				{#each medical as c (c.id)}
					<li>
						<span>{c.note}</span>
						<button type="button" class="btn btn-danger" onclick={() => removeConstraint(c.id)}>Remove</button>
					</li>
				{/each}
			</ul>
		{/if}
		<form class="inline-form" onsubmit={addMedical}>
			<input type="text" bind:value={newMedicalNote} placeholder="e.g. Type 2 diabetes" aria-label="Medical note" />
			<button type="submit" class="btn btn-secondary" disabled={addingMedical || !newMedicalNote.trim()}>
				{addingMedical ? 'Adding…' : 'Add'}
			</button>
		</form>
	</section>

	<section class="card constraint-section">
		<h2>Preferences</h2>
		<p class="muted field-note">
			Why this exists: a place for taste preferences that aren't allergies or requirements ("not a
			fan of cilantro", "trying to cut back on sugar") — informational only, shown on your profile,
			never auto-filtered. For anything you actually want removed from search and recipe results,
			use the allergies/intolerances section above with severity "avoid" instead.
		</p>
		{#if preferences.length > 0}
			<ul class="constraint-list">
				{#each preferences as c (c.id)}
					<li>
						<span>{c.note}</span>
						<button type="button" class="btn btn-danger" onclick={() => removeConstraint(c.id)}>Remove</button>
					</li>
				{/each}
			</ul>
		{/if}
		<form class="inline-form" onsubmit={addPreference}>
			<input
				type="text"
				bind:value={newPreferenceNote}
				placeholder="e.g. Not keen on cilantro"
				aria-label="Preference note"
			/>
			<button type="submit" class="btn btn-secondary" disabled={addingPreference || !newPreferenceNote.trim()}>
				{addingPreference ? 'Adding…' : 'Add'}
			</button>
		</form>
	</section>
{/if}

<style>
	.profile-form {
		max-width: 32rem;
		margin-bottom: var(--space-5);
	}
	.checkbox {
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: var(--space-2);
	}
	.field-note {
		margin-top: var(--space-1);
	}
	.constraint-section {
		max-width: 40rem;
		margin-bottom: var(--space-4);
	}
	.constraint-list {
		list-style: none;
		padding: 0;
		margin: var(--space-3) 0;
	}
	.constraint-list li {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
	}
	.constraint-list li:last-child {
		border-bottom: none;
	}
	.inline-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-3);
	}
	.inline-form select,
	.inline-form input {
		width: auto;
		flex: 1 1 10rem;
	}
</style>
