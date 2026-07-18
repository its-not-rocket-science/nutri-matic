<svelte:head>
	<title>Data & Methodology — Nutri-Matic</title>
	<meta
		name="description"
		content="Where every number in Nutri-Matic comes from: USDA sourcing, DIAAS/PDCAAS methodology, provenance, and confidence tiers."
	/>
</svelte:head>

<h1>Data &amp; methodology</h1>
<p><a href="/">&larr; Back</a></p>

<p class="intro">
	Where every number in this app comes from — what's directly sourced from a published dataset or
	standard, what's a documented estimate, and what isn't modelled at all. Nutri-Matic would rather
	tell you "we don't know" than quietly guess.
</p>

<section id="food-data">
	<h2>Food composition data</h2>
	<p>
		All food/nutrient data comes from <strong>USDA FoodData Central</strong> (FDC) CSV exports:
		Foundation Foods, SR Legacy, and Branded Foods. Nutrient amounts are USDA's own analytical or
		labelled values — not re-derived or adjusted.
	</p>
	<ul>
		<li>
			<strong>Foundation Foods / SR Legacy</strong> — whole/minimally-processed foods with USDA
			lab-analysed nutrient profiles. These are what amino acid and micronutrient data mostly comes
			from.
		</li>
		<li>
			<strong>Branded Foods</strong> — packaged/retail products, sourced from nutrition-facts-panel
			data submitted to USDA. This is what barcode scanning resolves against (the <code>gtin_upc</code>
			field). Branded foods essentially never have published amino acid data, so they can't be scored
			for DIAAS/PDCAAS — that's a real gap in the underlying data, not a bug.
		</li>
	</ul>
	<p>
		USDA nutrient numbers (<code>fdc_nutrient_nbr</code>) are verified directly against each
		dataset's own <code>nutrient.csv</code> rather than assumed stable — they aren't always: for
		example arachidonic acid's nutrient number differs between Foundation Foods and SR Legacy, and
		fibre is reported under two different lab methods depending on the food. Both are mapped
		explicitly rather than picking one and hoping.
	</p>
</section>

<section id="provenance">
	<h2>Provenance &amp; confidence</h2>
	<p>
		Every displayed value traces through the same chain: <strong>Food → FDC ID / dataset → USDA
		nutrient number → the FoodNutrient row → any recipe/diary aggregation → the DRV comparison</strong>.
		A food's own <code>/provenance</code> API endpoint exposes this chain directly (dataset, nutrient
		numbers, digestibility sources) for anyone who wants to check a number rather than trust it.
	</p>
	<p>
		Raw nutrient <em>amounts</em> are always exactly what USDA reported — this app never estimates or
		imputes a micronutrient amount; a food either has the row FDC gave it, or has no row for that
		nutrient at all. What actually varies in confidence is everything built <em>from</em> those
		amounts:
	</p>
	<ul>
		<li>
			<strong>Digestibility</strong> (DIAAS/PDCAAS) — <span class="badge badge-measured">measured</span>
			or <span class="badge badge-estimated">estimated</span>, as described above. For a recipe or a
			diary day, this is computed as the <em>weakest link</em> across every ingredient that
			contributed protein: the combined result is only <code>measured</code> if every contributing
			food's digestibility was; one estimated ingredient makes the whole combination
			<code>estimated</code>. This used to just be left blank for recipes ("a blend, not a single
			tag") — it's now computed for real.
		</li>
		<li>
			<strong>Iron haem/non-haem split</strong> — same measured/estimated tagging, described in the
			bioavailability section below.
		</li>
		<li>
			<strong>Daily reference values</strong> — tagged <code>live_confirmed</code> (this specific
			figure, or an increment on it, was independently checked against a live/primary source this
			session — currently vitamin A, retinol, calcium, and iron) or <code>secondary_source</code>
			(the default: sourced from the named RNI/PRI/RDA table via a secondary comparison table,
			consistently reproduced but not independently re-verified against the primary document
			page-by-page). Energy targets get their own tag,
			<code>personalized_calculation</code>, since they're computed live from your own profile
			rather than looked up from a population table at all.
		</li>
	</ul>
	<p class="muted">
		These are deliberately coarse, hand-set tiers describing real, checkable facts about how each
		value was sourced — not a fabricated numeric confidence score. A single number implying false
		precision would be worse than no number at all.
	</p>
</section>

<section id="live-vs-snapshot">
	<h2>Live vs Snapshot Mode</h2>
	<p>
		Every score and DRV comparison the API returns is stamped with a <code>methodology_version</code>
		(both a DRV-matrix version and a scoring version — see the badge on the diary page). By default,
		<strong>Live Mode</strong> is the only mode: every diary day is recomputed from current code and
		current data every time you look at it. If this app's methodology changes later — a corrected DRV
		figure, a new digestibility source, a scoring fix — a day you logged last month will reflect that
		change the next time you view it, not the methodology that was in effect when you logged it.
	</p>
	<p>
		<strong>Snapshot Mode</strong> is the opt-in alternative: from the diary page, you can explicitly
		freeze a day's full computed result, including the methodology versions in effect at that moment.
		A snapshot is immutable — taking one a second time is refused, and logging more food for that day
		afterward doesn't change it. This is what makes the methodology-version stamping actually
		<em>auditable</em>: without ever taking a snapshot, "methodology_version" is just a label on
		numbers that keep moving; with one, you have a fixed point to compare today's live numbers
		against.
	</p>
	<p class="muted">
		Snapshots are never taken automatically. A day you never explicitly snapshot only ever exists in
		Live Mode — this app doesn't claim to retroactively reconstruct the methodology that was in effect
		on a day before this feature existed, and won't pretend to.
	</p>
</section>

<section id="protein-quality">
	<h2>Protein quality (DIAAS / PDCAAS)</h2>
	<p>
		<strong>DIAAS</strong> (Digestible Indispensable Amino Acid Score) and <strong>PDCAAS</strong>
		(Protein Digestibility-Corrected Amino Acid Score) both compare a food's indispensable amino acid
		profile against a reference pattern, then correct for how digestible that protein actually is.
		The reference patterns (mg amino acid per g protein) are from
		<strong>FAO. 2013. Dietary protein quality evaluation in human nutrition</strong>, Table 4.1 —
		the current FAO/WHO standard.
	</p>
	<p>
		DIAAS uses per-amino-acid true ileal digestibility and is <em>not</em> capped at 100%. PDCAAS uses
		a single overall digestibility coefficient (typically faecal) and is capped at 100%, per standard
		convention.
	</p>
	<h3>Digestibility coefficients — two tiers, always labelled</h3>
	<p>
		Every score is tagged <span class="badge badge-measured">measured</span> or
		<span class="badge badge-estimated">estimated</span> so you always know which you're looking at:
	</p>
	<ul>
		<li>
			<strong>Measured</strong> — a real published digestibility study for that specific food.
			Deliberately a short list: egg and cooked chicken meat come from Kashyap et al. 2018 (<em
				>Am J Clin Nutr</em
			> 108(5):980-987, human ileal, dual stable isotope). A handful of PDCAAS values (rice, corn,
			oats, peanuts, soybeans, beans, lentils/chickpeas) come from the classic FAO (1991)
			<em>Protein Quality Evaluation</em> true-digestibility table, as widely reproduced in nutrition
			literature — rice was additionally cross-checked against an FAO document citing WHO
			1985/Hopkins 1981 human data.
		</li>
		<li>
			<strong>Estimated</strong> — a broad food-category coefficient (e.g. "meat" ≈ 0.90, "legumes" ≈
			0.80) applied when no food-specific measurement exists. This is a coarse approximation, not a
			citable number for that food — it exists so most ingested foods get <em>some</em> usable score
			rather than none.
		</li>
	</ul>
	<p class="muted">
		Missing amino acid or digestibility data isn't silently treated as zero — a food or recipe with
		an incomplete profile is reported as unscorable rather than given a number that understates it.
	</p>
</section>

<section id="vitamins-minerals">
	<h2>Vitamins, minerals, fibre &amp; fats — daily reference values</h2>
	<p>
		Each nutrient has up to four target values — adult male, adult female, pregnant, lactating — so
		gap analysis reflects your actual profile rather than one generic figure. Sourced in this
		priority order:
	</p>
	<ol>
		<li><strong>UK Reference Nutrient Intake (RNI)</strong>, where one exists</li>
		<li><strong>EFSA Population Reference Intake / Adequate Intake</strong>, next</li>
		<li><strong>US RDA/AI</strong>, as a last resort</li>
	</ol>
	<p>
		Confidence varies per nutrient and is tracked individually — hover any nutrient in the app for
		its specific source and confidence note (e.g. "UK RNI; pregnancy increment confirmed live" vs.
		"US RDA/AI — no UK or EFSA figure set, no confirmed sex split"). Where no pregnancy/lactation
		increment could be confidently found, that value explicitly falls back to the adult-female
		figure rather than an invented estimate.
	</p>
	<p class="muted">
		The public, signed-out food lookup always shows the adult-female baseline (no profile to
		personalize against). Diary, recipe, and trends views use your actual profile once signed in.
	</p>
</section>

<section id="bioavailability">
	<h2>Bioavailability estimate (iron, calcium:phosphorus)</h2>
	<p>
		The diary's per-meal iron absorption estimate and day-level calcium:phosphorus ratio are the
		most heavily caveated numbers in the app — nutrient bioavailability is genuinely complicated, and
		this uses a deliberately simplified model built from real published constants rather than a full
		research-grade algorithm.
	</p>
	<h3>Iron</h3>
	<ul>
		<li>
			Haem iron is fixed at <strong>25% absorption</strong>, and 40% of a meat/fish/poultry food's
			total iron is treated as haem — both constants from the Monsen algorithm (Monsen ER et al.
			1978, <em>Am J Clin Nutr</em> 31:134-141; adapted as Monsen &amp; Balintfy 1982). Recent work
			suggests the 40% figure itself varies by food source; used here anyway as the most widely-cited
			single value.
		</li>
		<li>
			Non-haem iron absorption uses a two-tier model: <strong>5%</strong> baseline, or
			<strong>10%</strong> "enhanced" if the meal has ≥25mg vitamin C (FAO's Human Vitamin and Mineral
			Requirements, 2004, Ch.13, recommends this as a per-meal target) or contains any
			meat/fish/poultry. This is an explicit simplification of Monsen's real bracketed model — the
			exact published bracket table couldn't be sourced — not a transcription of it.
		</li>
		<li>
			Real per-food haem/non-haem splits (when FDC reports them) are used when present and marked
			<span class="badge badge-measured">measured</span>; otherwise the 40% category split is used
			and marked <span class="badge badge-estimated">estimated</span>. In practice, essentially every
			food in this app's data today goes through the estimated path — FDC's heme/non-heme iron
			fields exist but aren't populated in the ingested datasets.
		</li>
		<li>Phytates, tannins, and polyphenols — real inhibitors of iron absorption — aren't modelled at all, because FDC doesn't track them as nutrients.</li>
	</ul>
	<h3>Calcium:phosphorus</h3>
	<p>
		ESPGHAN (European Society for Paediatric Gastroenterology Hepatology and Nutrition) recommends a
		1:1–2:1 calcium:phosphorus ratio by weight. More recent research (NHANES 2005-2006 cross-sectional
		data) found no association between this ratio and bone mineral density in older adults — the
		app presents the ratio as informational context, not a strict target, and says so in the
		guidance text itself.
	</p>
</section>

<section id="energy">
	<h2>Energy (calorie) target</h2>
	<p>
		Personalized daily energy targets use the <strong>Mifflin-St Jeor</strong> equation (the modern
		standard, more accurate than the older Harris-Benedict formula) times a standard activity-level
		multiplier:
	</p>
	<pre>men:   BMR = 10×weight_kg + 6.25×height_cm − 5×age + 5
women: BMR = 10×weight_kg + 6.25×height_cm − 5×age − 161</pre>
	<p>
		Pregnancy adds a flat +200 kcal/day (commonly-cited UK SACN figure, applied flat rather than
		trimester-aware for simplicity); lactation adds +500 kcal/day (first 6 months). This requires
		weight, height, birth year, sex, and activity level all set in your profile — without all five,
		no target is shown rather than a guessed one.
	</p>
</section>

<section id="weight-loss-target">
	<h2>Weight-loss calorie target</h2>
	<p>
		If your profile goal is set to <strong>"Lose weight"</strong> or <strong>"Reduce visceral
		fat"</strong>, recipe and diary calorie targets switch from plain maintenance EER (above) to a
		deficit target — shown with a visible note wherever it appears, never applied silently.
	</p>
	<ul>
		<li>
			<strong>Deficit size:</strong> 15% below EER for adults, reduced to 10% for adults 65+. Older
			adults restricting calories are at greater risk of losing lean mass alongside fat — a concern
			well documented in geriatric nutrition literature (e.g. Villareal et al. 2011, <em>New England
			Journal of Medicine</em>, on combined diet-and-exercise weight-loss interventions in older
			adults) — so a smaller, more conservative deficit is used.
		</li>
		<li>
			<strong>Where 15% comes from:</strong> not a single official number from one governing body —
			it sits inside the commonly-reproduced "moderate, sustainable" ~10-20% range used across
			mainstream sports-nutrition/dietetics guidance for general (non-athlete, non-clinical) fat
			loss. More conservative than 20-25%+ (typically recommended only under direct supervision),
			and often smaller than the popular "500kcal/day" rule of thumb, which is itself a
			<em>larger</em> percentage for anyone below-average maintenance calories, since it's a flat
			number rather than a %. Treat 15%/10% as a reasonable, safety-conscious default, not a
			clinical prescription — nothing in this app can know if a larger or smaller deficit is
			actually right for you.
		</li>
		<li>
			<strong>Safety floor:</strong> the target never goes below 1,200 kcal/day (women) or 1,500
			kcal/day (men) — minimums commonly reproduced in NIH/NHLBI-style guidance and widely echoed by
			registered-dietitian sources as the point below which unsupervised dieting risks
			micronutrient inadequacy. Whichever number — the % deficit or the floor — is higher wins, so
			the floor only ever raises the target back up, never lowers it further.
		</li>
		<li>
			<strong>Pregnancy/lactation:</strong> never deficit-adjusted, regardless of goal — active
			calorie restriction during pregnancy or lactation isn't generally considered safe without
			direct clinical supervision, so these profiles always see plain EER (which already includes
			the flat pregnancy/lactation increments above).
		</li>
		<li>
			<strong>"Reduce visceral fat" uses the exact same calculation as "Lose weight".</strong>
			Visceral fat responds to the same overall energy-deficit mechanism as fat anywhere else in
			the body — there's no established way to calorie-target one fat depot over another, and
			inventing a different number for it would be exactly the fabricated precision this app avoids
			everywhere else.
		</li>
	</ul>
	<p class="muted">
		This is a default, not a recommendation tailored to you — if you have a specific medical
		reason to eat more or less than this, or a condition where calorie restriction isn't
		appropriate, talk to a doctor or registered dietitian rather than relying on this figure.
	</p>
</section>

<section id="food-chemistry">
	<h2>Sodium:potassium ratio, leucine threshold, protein distribution, absorbed protein</h2>
	<p>
		Four more diary checks, each computed from data already tracked rather than anything new:
	</p>
	<ul>
		<li>
			<strong>Sodium:potassium ratio</strong> — WHO recommends less than 2000mg sodium and at least
			3510mg potassium per day, implying a target ratio around 0.57. Both nutrients are directly
			tracked from FDC, so this is a real ratio against a real published target — presented as
			context, not a pass/fail grade.
		</li>
		<li>
			<strong>Leucine threshold</strong> — the minimum leucine in a single meal to maximally
			stimulate muscle protein synthesis, from Norton &amp; Layman (2006) and widely reproduced
			since: ~2.5g for younger adults, ~3g for older adults (age 65+, reflecting anabolic
			resistance). Computed from each meal's actual logged foods' leucine content; defaults to the
			lower, younger-adult threshold if your profile has no birth year set.
		</li>
		<li>
			<strong>Protein distribution</strong> — the same leucine-threshold check applied to every meal
			of the day, so you can see whether protein is spread out enough to clear the threshold more
			than once, rather than concentrated into a single meal (research, e.g. Mamerow et al. 2014,
			associates even distribution with better muscle protein synthesis than the same daily total
			skewed into one meal).
		</li>
		<li>
			<strong>Total absorbed protein</strong> — the day's total protein weighted by DIAAS/PDCAAS
			digestibility, i.e. how much actually gets absorbed rather than the raw "protein on the
			label" figure. DIAAS uses the digestibility of whichever amino acid is limiting that day's
			mix (the one that governs protein synthesis capacity); PDCAAS already reduces to one overall
			coefficient. Either is left blank if that method's digestibility data is incomplete for the
			day's foods — never guessed. Compared against a personalized daily target: body weight ×
			an activity-level figure (0.8g/kg sedentary up to 1.6g/kg very active — commonly reproduced
			sports-nutrition ranges, not one official table), with a 1.0g/kg floor for healthy adults 65+
			(PROT-AGE Study Group, Bauer et al. 2013 — countering age-related anabolic resistance) and a
			flat +6g/+11g increment for pregnancy/lactation (UK COMA/SACN). Needs weight, birth year, and
			activity level set in your profile; otherwise shown without a %.
		</li>
	</ul>
	<p class="muted">
		Not implemented: phytates, oxalates, and tannins. USDA FoodData Central doesn't track any of
		them as nutrients, so there's nothing to compute from — see "What this app doesn't do" below.
	</p>
</section>

<section id="budget">
	<h2>Grocery budget estimate</h2>
	<p>
		Prices are <strong>entirely user-entered</strong> — this app doesn't call any grocery-pricing API
		or database. You tell it what a package actually costs (price + package size) for a food you buy;
		the weekly shopping list multiplies that out against what your meal plan needs. Foods with no
		price set are shown as missing, not defaulted to zero or estimated from anywhere else.
	</p>
</section>

<section id="limitations">
	<h2>What this app doesn't do</h2>
	<ul>
		<li>No phytate, tannin, oxalate, or polyphenol data — real inhibitors of mineral absorption that FDC simply doesn't track.</li>
		<li>Branded/packaged foods can't be scored for protein quality — nutrition labels don't publish amino acid profiles.</li>
		<li>"Estimated" digestibility and iron-split values are broad category averages, not measurements of the specific food in front of you.</li>
		<li>DRV confidence varies a lot by nutrient — some increments are confirmed against a live source, others are commonly-cited figures recalled from secondary sources. Hover any nutrient for its specific note.</li>
		<li>This is a personal nutrition-tracking tool, not medical advice — bioavailability and DRV figures are population-level estimates, not individualized clinical guidance.</li>
	</ul>
</section>

<style>
	.intro {
		max-width: 40rem;
		color: var(--color-text-muted);
	}
	section {
		max-width: 40rem;
		margin: var(--space-6) 0;
	}
	h3 {
		margin-bottom: var(--space-2);
	}
	.muted {
		font-size: var(--font-size-sm);
	}
	code {
		background: var(--color-surface-muted);
		padding: 0.1em 0.3em;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-sm);
	}
	pre {
		background: var(--color-surface-muted);
		padding: var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--font-size-sm);
		overflow-x: auto;
	}
</style>
