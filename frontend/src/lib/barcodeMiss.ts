import { HttpError } from './api';

/** Shown above the food name search when a scanned or typed barcode is not
 * in the catalogue (docs/plans/canonical-foods-plan.md, PR 2). The catalogue
 * is USDA FoodData Central, so most UK products are not in it. */
export const BARCODE_MISS_HINT = 'Not in our database. Most products are US-listed. Search by name instead.';

/** True only for "no food for that barcode" (404). Network errors and other
 * failures are real errors and keep showing as errors. */
export function isBarcodeMiss(e: unknown): boolean {
	return e instanceof HttpError && e.status === 404;
}
