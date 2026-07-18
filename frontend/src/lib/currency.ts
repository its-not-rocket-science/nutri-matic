// Common region -> ISO 4217 currency code, used to default from the
// browser's own locale when the user hasn't set an explicit preference in
// their profile. Not exhaustive — falls back to USD for anything unmapped.
const REGION_CURRENCY: Record<string, string> = {
	US: 'USD',
	GB: 'GBP',
	IE: 'EUR',
	DE: 'EUR',
	FR: 'EUR',
	IT: 'EUR',
	ES: 'EUR',
	NL: 'EUR',
	BE: 'EUR',
	AT: 'EUR',
	PT: 'EUR',
	FI: 'EUR',
	GR: 'EUR',
	LU: 'EUR',
	CA: 'CAD',
	AU: 'AUD',
	NZ: 'NZD',
	JP: 'JPY',
	CN: 'CNY',
	IN: 'INR',
	BR: 'BRL',
	MX: 'MXN',
	CH: 'CHF',
	SE: 'SEK',
	NO: 'NOK',
	DK: 'DKK',
	PL: 'PLN',
	CZ: 'CZK',
	ZA: 'ZAR',
	RU: 'RUB',
	KR: 'KRW',
	SG: 'SGD',
	HK: 'HKD',
	TW: 'TWD',
	TH: 'THB',
	ID: 'IDR',
	MY: 'MYR',
	PH: 'PHP',
	VN: 'VND',
	TR: 'TRY',
	AE: 'AED',
	SA: 'SAR',
	IL: 'ILS',
	EG: 'EGP',
	NG: 'NGN',
	KE: 'KES',
	AR: 'ARS',
	CL: 'CLP',
	CO: 'COP',
	PE: 'PEN'
};

// Offered in the profile's currency picker — a curated subset of the above,
// not every ISO 4217 code that exists.
export const CURRENCY_OPTIONS: { code: string; label: string }[] = [
	{ code: 'USD', label: 'US Dollar (USD)' },
	{ code: 'GBP', label: 'British Pound (GBP)' },
	{ code: 'EUR', label: 'Euro (EUR)' },
	{ code: 'CAD', label: 'Canadian Dollar (CAD)' },
	{ code: 'AUD', label: 'Australian Dollar (AUD)' },
	{ code: 'NZD', label: 'New Zealand Dollar (NZD)' },
	{ code: 'JPY', label: 'Japanese Yen (JPY)' },
	{ code: 'CNY', label: 'Chinese Yuan (CNY)' },
	{ code: 'INR', label: 'Indian Rupee (INR)' },
	{ code: 'BRL', label: 'Brazilian Real (BRL)' },
	{ code: 'MXN', label: 'Mexican Peso (MXN)' },
	{ code: 'CHF', label: 'Swiss Franc (CHF)' },
	{ code: 'SEK', label: 'Swedish Krona (SEK)' },
	{ code: 'NOK', label: 'Norwegian Krone (NOK)' },
	{ code: 'DKK', label: 'Danish Krone (DKK)' },
	{ code: 'PLN', label: 'Polish Zloty (PLN)' },
	{ code: 'ZAR', label: 'South African Rand (ZAR)' },
	{ code: 'KRW', label: 'South Korean Won (KRW)' },
	{ code: 'SGD', label: 'Singapore Dollar (SGD)' },
	{ code: 'HKD', label: 'Hong Kong Dollar (HKD)' },
	{ code: 'RUB', label: 'Russian Ruble (RUB)' },
	{ code: 'TRY', label: 'Turkish Lira (TRY)' },
	{ code: 'AED', label: 'UAE Dirham (AED)' },
	{ code: 'ILS', label: 'Israeli Shekel (ILS)' }
];

function browserRegion(): string | undefined {
	if (typeof navigator === 'undefined' || !navigator.language) return undefined;
	try {
		// Intl.Locale resolves a bare language tag ("en") to its most likely
		// region ("US") the same way a bare "-GB" suffix would be read directly
		return new Intl.Locale(navigator.language).maximize().region;
	} catch {
		const parts = navigator.language.split('-');
		return parts.length > 1 ? parts[1].toUpperCase() : undefined;
	}
}

/** The currency this browser's locale implies — the default only when the
 * user hasn't set an explicit currency preference in their profile. */
export function browserDefaultCurrency(): string {
	const region = browserRegion();
	return (region && REGION_CURRENCY[region]) || 'USD';
}

/** Which currency to actually use: the user's explicit profile preference,
 * or the browser locale's implied currency if they haven't set one. */
export function resolveCurrency(userCurrency: string | null | undefined): string {
	return userCurrency || browserDefaultCurrency();
}

/** Formats an amount in the resolved currency, using the browser's own
 * locale for symbol placement/decimal style — e.g. "$12.34", "£12.34",
 * "12,34 €" — so it matches what the user's browser is already set to. */
export function formatCurrency(amount: number, userCurrency: string | null | undefined): string {
	const currency = resolveCurrency(userCurrency);
	const locale = typeof navigator !== 'undefined' ? navigator.language : undefined;
	try {
		return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount);
	} catch {
		// an unrecognized currency code would throw — fall back to a plain
		// number rather than crashing the page over a display nicety
		return amount.toFixed(2);
	}
}

/** Just the symbol (e.g. "$", "£", "€") for inline labels like "Package price ($)". */
export function currencySymbol(userCurrency: string | null | undefined): string {
	const currency = resolveCurrency(userCurrency);
	const locale = typeof navigator !== 'undefined' ? navigator.language : undefined;
	try {
		const parts = new Intl.NumberFormat(locale, { style: 'currency', currency }).formatToParts(0);
		return parts.find((p) => p.type === 'currency')?.value ?? currency;
	} catch {
		return currency;
	}
}
