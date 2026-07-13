<button type="button" class="no-print" onclick={() => window.print()}>Print / Save as PDF</button>

<style>
	@media print {
		.no-print {
			display: none !important;
		}
	}
</style>
