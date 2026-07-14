<script lang="ts">
	let { href, label = 'About this data' }: { href: string; label?: string } = $props();
</script>

<a class="info-link" {href} title={label} aria-label={label}>ⓘ</a>

<style>
	.info-link {
		display: inline-block;
		text-decoration: none;
		font-size: 0.85em;
		margin-left: 0.3em;
		color: #3a6ea5;
	}
</style>
