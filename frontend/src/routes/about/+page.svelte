<svelte:head>
	<title>About — Nutri-Matic</title>
	<meta
		name="description"
		content="Why Nutri-Matic is called that, what it actually measures, and its measure-don't-guess philosophy."
	/>
</svelte:head>

<h1>About Nutri-Matic</h1>
<p><a href="/">&larr; Back</a></p>

<p class="intro">
	A machine, built with total scientific confidence, that analyses what's in front of you and
	tells you exactly what it found. That premise has one famous ancestor — and one very different
	ending.
</p>

<section id="the-name">
	<h2>The name</h2>
	<p>
		Douglas Adams' <em>The Hitchhiker's Guide to the Galaxy</em> has a machine that takes its job
		extremely seriously — analysing molecular structure, spectral signatures, and personality in
		order to synthesise exactly the beverage you're craving — and, having done all that
		genuinely impressive science, gets the one thing that matters completely wrong. It's a joke
		about instruments that are rigorous everywhere except the part you actually needed.
	</p>
	<p>
		This app borrows the premise, not the punchline. Nutri-Matic takes a bowl of chickpeas as
		seriously as a mass spectrometer would — provenance-tracked amino acid profiles, digestibility
		coefficients cited to the study, reference values checked against a primary source — and then
		tries very hard not to get the one thing that matters wrong. Where it can't be sure, it says
		so, tagged and visible, rather than quietly serving you a confident number. No Hitchhiker's
		Guide text, characters, or branding appear anywhere in this app; the inheritance is the tone
		of the joke, not its content.
	</p>
</section>

<section id="what-it-does">
	<h2>What it actually does</h2>
	<p>
		Nutri-Matic is a protein-quality and micronutrient analysis tool — not a calorie counter. Log
		a food or a meal and it computes DIAAS/PDCAAS (how complete and digestible its protein
		actually is), tracks bioavailability-adjusted vitamins and minerals against your personal
		reference values, and — if a food falls short somewhere — suggests a real pairing or swap,
		simulated and scored against your own data rather than pattern-matched from a generic list.
	</p>
	<p>
		Every one of those numbers traces back to a USDA FoodData Central record, a named study, or an
		explicitly-labelled category estimate. See <a href="/methodology">Data &amp; Methodology</a>
		for the full chain.
	</p>
</section>

<section id="philosophy">
	<h2>Measure, don't guess</h2>
	<p>
		The operating rule is simple: a number is either sourced or it doesn't appear. Missing amino
		acid data isn't silently treated as zero; an estimated digestibility coefficient is labelled
		<span class="badge badge-estimated">estimated</span>, never presented the same way as a
		<span class="badge badge-measured">measured</span> one; a food with an incomplete profile is
		reported as unscorable rather than given a number that understates it. "We don't know" is a
		valid, frequently-used answer in this app.
	</p>
	<p class="muted">
		That standard is described in full, nutrient by nutrient, on the
		<a href="/methodology">Data &amp; Methodology</a> page — including where the science itself is
		still genuinely unsettled (bioavailability modelling, in particular, is a deliberately
		simplified estimate of a very complicated reality, and is labelled as such throughout).
	</p>
</section>

<style>
	.intro {
		max-width: 40rem;
		color: var(--color-text-muted);
		font-size: var(--font-size-md);
	}
	section {
		max-width: 40rem;
		margin: var(--space-6) 0;
	}
</style>
