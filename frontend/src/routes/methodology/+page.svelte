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
		color: #444;
	}
	section {
		max-width: 40rem;
		margin: 2rem 0;
	}
	h3 {
		margin-bottom: 0.4rem;
	}
	.muted {
		color: #666;
		font-size: 0.9em;
	}
	code {
		background: #f5f5f5;
		padding: 0.1em 0.3em;
		border-radius: 3px;
		font-size: 0.9em;
	}
	pre {
		background: #f5f5f5;
		padding: 0.75rem;
		border-radius: 4px;
		font-size: 0.9em;
		overflow-x: auto;
	}
	.badge {
		display: inline-block;
		font-size: 0.85em;
		padding: 0.1em 0.5em;
		border-radius: 999px;
	}
	.badge-measured {
		background: #dff0d8;
		color: #2d6a2d;
	}
	.badge-estimated {
		background: #fdf3d0;
		color: #8a6d00;
	}
</style>
