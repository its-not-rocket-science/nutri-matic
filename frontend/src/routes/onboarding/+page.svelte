<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FoodSearchInput from '$lib/components/FoodSearchInput.svelte';
	import type { DietaryVocabulary, Food, Meal, MealOptimization, User } from '$lib/types';

	function toIsoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}
	function guessCurrentMeal(): Meal {
		const hour = new Date().getHours();
		if (hour < 11) return 'breakfast';
		if (hour < 15) return 'lunch';
		if (hour < 20) return 'dinner';
		return 'snack';
	}

	const STEP_LABELS = ['Goal', 'Profile', 'Dietary requirements', 'First meal', 'First optimisation'];
	let step = $state(1);

	// Step 1 — goal (not persisted; just personalizes the closing message)
	type Goal = 'protein_quality' | 'nutrient_gaps' | 'budget' | 'exploring';
	let goal: Goal | null = $state(null);

	// Step 2 — profile basics
	let sex: User['sex'] = $state(null);
	let birthYear: number | null = $state(null);
	let activityLevel: User['activity_level'] = $state(null);
	let weightKg: number | null = $state(null);
	let heightCm: number | null = $state(null);
	let savingProfile = $state(false);
	let profileError: string | null = $state(null);

	// Step 3 — dietary requirements
	let vocabulary: DietaryVocabulary | null = $state(null);
	let dietaryPattern: string | null = $state(null);
	let allergyTag = $state('');
	let savingDietary = $state(false);
	let dietaryError: string | null = $state(null);

	// Step 4 — first meal
	let selectedFood: Food | null = $state(null);
	let quantityG = $state(100);
	const meal: Meal = guessCurrentMeal();
	let loggingMeal = $state(false);
	let mealError: string | null = $state(null);

	// Step 5 — first optimisation
	let optimization: MealOptimization | null = $state(null);
	let loadingOptimization = $state(false);
	let optimizationError: string | null = $state(null);

	const todayIso = toIsoDate(new Date());

	const goalMessage: Record<Goal, string> = {
		protein_quality: "You're set up to track DIAAS/PDCAAS on everything you log — check the score on your first meal below.",
		nutrient_gaps: "Your dashboard will always lead with today's biggest nutrient gap and a real food to close it.",
		budget: 'Add prices under Food Prices any time — the meal-plan optimiser will factor real cost into every suggestion.',
		exploring: 'Have a look around — nothing here is locked behind a purchase, and every number traces back to its source.'
	};

	onMount(async () => {
		if (!auth.isLoggedIn) {
			await goto('/login');
			return;
		}
		vocabulary = await api.getDietaryVocabulary();
	});

	async function saveProfileStep() {
		savingProfile = true;
		profileError = null;
		try {
			const updated = await api.updateProfile({
				sex,
				birth_year: birthYear,
				activity_level: activityLevel,
				is_pregnant: false,
				is_lactating: false,
				weight_kg: weightKg,
				height_cm: heightCm,
				dietary_pattern: null
			});
			auth.setUser(updated);
			step = 3;
		} catch (e) {
			profileError = e instanceof Error ? e.message : String(e);
		} finally {
			savingProfile = false;
		}
	}

	async function saveDietaryStep() {
		savingDietary = true;
		dietaryError = null;
		try {
			const updated = await api.updateProfile({
				sex,
				birth_year: birthYear,
				activity_level: activityLevel,
				is_pregnant: false,
				is_lactating: false,
				weight_kg: weightKg,
				height_cm: heightCm,
				dietary_pattern: dietaryPattern
			});
			auth.setUser(updated);
			if (allergyTag) {
				await api.createDietaryConstraint({
					category: 'allergy',
					tag: allergyTag,
					severity: 'hard_exclude',
					note: null
				});
			}
			step = 4;
		} catch (e) {
			dietaryError = e instanceof Error ? e.message : String(e);
		} finally {
			savingDietary = false;
		}
	}

	async function logFirstMeal() {
		if (!selectedFood) return;
		loggingMeal = true;
		mealError = null;
		try {
			await api.addDiaryEntry({
				entry_date: todayIso,
				meal,
				food_id: selectedFood.id,
				quantity_g: quantityG
			});
			step = 5;
			loadingOptimization = true;
			try {
				optimization = await api.getMealOptimization(todayIso, meal);
			} catch (e) {
				optimizationError = e instanceof Error ? e.message : String(e);
			} finally {
				loadingOptimization = false;
			}
		} catch (e) {
			mealError = e instanceof Error ? e.message : String(e);
		} finally {
			loggingMeal = false;
		}
	}

	function skipToStep(n: number) {
		step = n;
	}
</script>

<div class="onboarding">
	<p class="label-caps">Step {step} of 5 &middot; {STEP_LABELS[step - 1]}</p>
	<div class="progress-track">
		<div class="progress-fill" style="width: {(step / 5) * 100}%"></div>
	</div>

	{#if step === 1}
		<h1>Welcome to Nutri-Matic</h1>
		<p class="muted">
			An instrument for measuring protein quality and micronutrient sufficiency — not a calorie
			counter. Five quick steps, then straight to your dashboard.
		</p>
		<div class="card goal-grid">
			{#each [['protein_quality', 'Track protein quality'], ['nutrient_gaps', 'Close nutrient gaps'], ['budget', 'Plan meals on a budget'], ['exploring', 'Just exploring']] as [key, label] (key)}
				<button
					type="button"
					class="btn goal-option"
					class:selected={goal === key}
					onclick={() => (goal = key as Goal)}
				>
					{label}
				</button>
			{/each}
		</div>
		<div class="wizard-actions">
			<button type="button" class="btn btn-primary" disabled={!goal} onclick={() => (step = 2)}>
				Continue
			</button>
		</div>
	{:else if step === 2}
		<h1>A little about you</h1>
		<p class="muted">
			Used to select the right reference values for your diary and compute a personalised calorie
			target — skip anything you'd rather not share, nothing here is required to use the app.
		</p>
		<form class="card" onsubmit={(e) => { e.preventDefault(); saveProfileStep(); }}>
			<div class="field">
				<label for="ob-sex">Sex</label>
				<select id="ob-sex" bind:value={sex}>
					<option value={null}>Prefer not to say</option>
					<option value="female">Female</option>
					<option value="male">Male</option>
				</select>
			</div>
			<div class="field">
				<label for="ob-birth-year">Birth year</label>
				<input id="ob-birth-year" type="number" min="1900" max="2026" bind:value={birthYear} />
			</div>
			<div class="field">
				<label for="ob-activity">Activity level</label>
				<select id="ob-activity" bind:value={activityLevel}>
					<option value={null}>Not set</option>
					<option value="sedentary">Sedentary</option>
					<option value="light">Lightly active</option>
					<option value="moderate">Moderately active</option>
					<option value="active">Active</option>
					<option value="very_active">Very active</option>
				</select>
			</div>
			<div class="field">
				<label for="ob-weight">Weight (kg)</label>
				<input id="ob-weight" type="number" step="any" min="0" bind:value={weightKg} />
			</div>
			<div class="field">
				<label for="ob-height">Height (cm)</label>
				<input id="ob-height" type="number" step="any" min="0" bind:value={heightCm} />
			</div>
			{#if profileError}
				<p class="error">{profileError}</p>
			{/if}
			<div class="wizard-actions">
				<button type="button" class="btn btn-secondary" onclick={() => (step = 1)}>Back</button>
				<button type="button" class="btn btn-secondary" onclick={() => skipToStep(3)}>Skip</button>
				<button type="submit" class="btn btn-primary" disabled={savingProfile}>
					{savingProfile ? 'Saving…' : 'Continue'}
				</button>
			</div>
		</form>
	{:else if step === 3}
		<h1>Dietary requirements</h1>
		<p class="muted">
			Applied as a hard exclusion everywhere foods are suggested — search, recipes, meal planning,
			the optimiser. Add more any time from your profile.
		</p>
		{#if vocabulary}
			<form class="card" onsubmit={(e) => { e.preventDefault(); saveDietaryStep(); }}>
				<div class="field">
					<label for="ob-pattern">Dietary pattern</label>
					<select id="ob-pattern" bind:value={dietaryPattern}>
						<option value={null}>Not set</option>
						{#each vocabulary.dietary_patterns as p (p.key)}
							<option value={p.key}>{p.label}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="ob-allergy">Any allergy to flag now? (optional)</label>
					<select id="ob-allergy" bind:value={allergyTag}>
						<option value="">None right now</option>
						{#each vocabulary.allergen_tags as t (t.key)}
							<option value={t.key}>{t.label}</option>
						{/each}
					</select>
				</div>
				{#if dietaryError}
					<p class="error">{dietaryError}</p>
				{/if}
				<div class="wizard-actions">
					<button type="button" class="btn btn-secondary" onclick={() => (step = 2)}>Back</button>
					<button type="button" class="btn btn-secondary" onclick={() => skipToStep(4)}>Skip</button>
					<button type="submit" class="btn btn-primary" disabled={savingDietary}>
						{savingDietary ? 'Saving…' : 'Continue'}
					</button>
				</div>
			</form>
		{/if}
	{:else if step === 4}
		<h1>Log your first meal</h1>
		<p class="muted">Search for anything — even a plain ingredient works. This is what the whole app runs on.</p>
		<div class="card">
			{#if selectedFood}
				<p>
					Selected: <strong>{selectedFood.name}</strong>
					<button type="button" class="btn btn-secondary" onclick={() => (selectedFood = null)}>Change</button>
				</p>
				<div class="field">
					<label for="ob-quantity">Quantity (g)</label>
					<input id="ob-quantity" type="number" step="any" min="0" bind:value={quantityG} />
				</div>
			{:else}
				<FoodSearchInput onSelect={(food) => (selectedFood = food)} label="Search foods" />
			{/if}
			{#if mealError}
				<p class="error">{mealError}</p>
			{/if}
			<div class="wizard-actions">
				<button type="button" class="btn btn-secondary" onclick={() => (step = 3)}>Back</button>
				<button type="button" class="btn btn-secondary" onclick={() => goto('/')}>Skip for now</button>
				<button
					type="button"
					class="btn btn-primary"
					disabled={!selectedFood || loggingMeal}
					onclick={logFirstMeal}
				>
					{loggingMeal ? 'Logging…' : `Log to ${meal}`}
				</button>
			</div>
		</div>
	{:else if step === 5}
		<h1>Nicely done.</h1>
		{#if goal}
			<p class="muted">{goalMessage[goal]}</p>
		{/if}
		<div class="card">
			<p class="label-caps">Highest-impact recommendation</p>
			{#if loadingOptimization}
				<p class="muted">Calibrating…</p>
			{:else if optimizationError}
				<p class="error">{optimizationError}</p>
			{:else if optimization && optimization.suggestions.length > 0}
				{@const top = optimization.suggestions[0]}
				<h3>+{top.improvement.toFixed(1)}pp <span class="muted">{optimization.target_nutrient_name}</span></h3>
				<p>
					{#if top.action === 'swap'}
						Swap <strong>{top.replaces_food_name}</strong> &rarr; <strong>{top.food_name}</strong> ({top.quantity_g}g)
					{:else}
						Add <strong>{top.quantity_g}g {top.food_name}</strong>
					{/if}
				</p>
				<p class="muted">
					{top.before_percent_drv.toFixed(0)}% &rarr; {top.after_percent_drv.toFixed(0)}% of target
				</p>
			{:else}
				<p class="muted">
					Nothing to optimise yet with just one food logged — this is exactly what the optimiser
					on your dashboard will do once you've logged a full meal.
				</p>
			{/if}
		</div>
		<div class="wizard-actions">
			<button type="button" class="btn btn-primary" onclick={() => goto('/')}>Go to dashboard &rarr;</button>
		</div>
	{/if}
</div>

<style>
	.onboarding {
		max-width: 34rem;
		margin: 0 auto;
	}
	.progress-track {
		height: 0.35rem;
		background: var(--color-surface-muted);
		border-radius: var(--radius-full);
		margin: var(--space-2) 0 var(--space-6);
		overflow: hidden;
	}
	.progress-fill {
		height: 100%;
		background: var(--color-primary);
		transition: width 0.2s ease;
	}
	.goal-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
		gap: var(--space-3);
	}
	.goal-option {
		text-transform: none;
		font-family: var(--font-sans);
		letter-spacing: normal;
		background: var(--color-surface);
		border-color: var(--color-border);
		color: var(--color-text);
		justify-content: flex-start;
		text-align: left;
		padding: var(--space-4);
		height: auto;
	}
	.goal-option.selected {
		border-color: var(--color-primary);
		background: var(--color-primary-subtle);
		color: var(--color-primary);
		font-weight: var(--font-weight-medium);
	}
	.wizard-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
</style>
