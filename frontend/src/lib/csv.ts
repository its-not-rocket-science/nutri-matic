/** Triggers a browser download of `rows` as a CSV file — no library, just a Blob + a synthetic click. */
export function downloadCsv(filename: string, rows: (string | number | null | undefined)[][]): void {
	const csv = rows
		.map((row) =>
			row
				.map((cell) => {
					const value = cell === null || cell === undefined ? '' : String(cell);
					return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
				})
				.join(',')
		)
		.join('\r\n');

	const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	URL.revokeObjectURL(url);
}
