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
			<button type="button" class="close-btn" onclick={handleClose} aria-label="Close scanner">&times;</button>
		</div>

		<video bind:this={videoEl} class="preview" muted playsinline></video>

		{#if cameraError}
			<p class="error">Camera unavailable: {cameraError}</p>
		{/if}

		<form onsubmit={handleManualSubmit}>
			<div class="field">
				<label for="manual-barcode">Or enter the barcode manually</label>
				<input
					id="manual-barcode"
					type="text"
					inputmode="numeric"
					bind:value={manualBarcode}
					placeholder="e.g. 012345678905"
				/>
			</div>
			<button type="submit" class="btn btn-primary" disabled={!manualBarcode.trim()}>Look up</button>
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
		background: var(--color-surface);
		border-radius: var(--radius-md);
		padding: var(--space-4);
		width: min(90vw, 28rem);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		box-shadow: var(--shadow-lg);
	}
	.scanner-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.scanner-header h3 {
		margin: 0;
	}
	.close-btn {
		font-size: 1.2rem;
		line-height: 1;
		background: none;
		border: none;
		cursor: pointer;
		color: var(--color-text);
		min-height: 2.75rem;
		min-width: 2.75rem;
	}
	.preview {
		width: 100%;
		max-height: 60vh;
		background: #000;
		border-radius: var(--radius-sm);
	}
</style>
