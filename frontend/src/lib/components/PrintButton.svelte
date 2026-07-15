<button type="button" class="btn btn-secondary no-print" onclick={() => window.print()}>Print / Save as PDF</button>

<style>
	@media print {
		.no-print {
			display: none !important;
		}
	}
</style>
