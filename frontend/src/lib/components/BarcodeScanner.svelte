<script lang="ts">
	import { onDestroy } from 'svelte';
	import { BrowserMultiFormatReader } from '@zxing/browser';
	import type { IScannerControls } from '@zxing/browser';

	let { onScan, onClose }: { onScan: (barcode: string) => void; onClose: () => void } = $props();

	let videoEl: HTMLVideoElement | undefined = $state();
	let cameraError: string | null = $state(null);
	let manualBarcode = $state('');
	let controls: IScannerControls | null = null;

	async function startCamera() {
		cameraError = null;
		try {
			const reader = new BrowserMultiFormatReader();
			controls = await reader.decodeFromVideoDevice(undefined, videoEl!, (result, err) => {
				if (result) {
					stopCamera();
					onScan(result.getText());
				}
				// err fires continuously while no barcode is in frame — not a real error, ignore
			});
		} catch (e) {
			cameraError = e instanceof Error ? e.message : String(e);
		}
	}

	function stopCamera() {
		controls?.stop();
		controls = null;
	}

	function handleManualSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (!manualBarcode.trim()) return;
		stopCamera();
		onScan(manualBarcode.trim());
	}

	function handleClose() {
		stopCamera();
		onClose();
	}

	$effect(() => {
		if (videoEl) startCamera();
	});

	onDestroy(stopCamera);
</script>

<div class="scanner-overlay">
	<div class="scanner-box">
		<div class="scanner-header">
			<h3>Scan barcode</h3>
			<button type="button" onclick={handleClose}>&times;</button>
		</div>

		<video bind:this={videoEl} class="preview" muted playsinline></video>

		{#if cameraError}
			<p class="error">Camera unavailable: {cameraError}</p>
		{/if}

		<form onsubmit={handleManualSubmit}>
			<label>
				Or enter the barcode manually
				<input type="text" inputmode="numeric" bind:value={manualBarcode} placeholder="e.g. 012345678905" />
			</label>
			<button type="submit" disabled={!manualBarcode.trim()}>Look up</button>
		</form>
	</div>
</div>

<style>
	.scanner-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}
	.scanner-box {
		background: white;
		border-radius: 8px;
		padding: 1rem;
		width: min(90vw, 28rem);
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.scanner-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.scanner-header h3 {
		margin: 0;
	}
	.scanner-header button {
		font-size: 1.2rem;
		line-height: 1;
		background: none;
		border: none;
		cursor: pointer;
	}
	.preview {
		width: 100%;
		max-height: 60vh;
		background: #000;
		border-radius: 4px;
	}
	.error {
		color: #b00020;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
</style>
