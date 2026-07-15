<script lang="ts">
	let { href, label = 'About this data' }: { href: string; label?: string } = $props();
</script>

<a class="info-link" {href} title={label} aria-label={label}>ⓘ</a>

<style>
	.info-link {
		display: inline-block;
		text-decoration: none;
		font-size: var(--font-size-sm);
		margin-left: 0.3em;
		color: var(--color-primary);
	}
</style>
