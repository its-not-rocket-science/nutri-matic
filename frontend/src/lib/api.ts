import type { Food, FoodCreate, Score } from './types';

const API_URL = import.meta.env.VITE_API_URL;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const res = await fetch(`${API_URL}${path}`, {
		headers: { 'Content-Type': 'application/json' },
		...options
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(body.detail ?? `Request failed: ${res.status}`);
	}
	return res.json();
}

export const api = {
	listFoods: () => request<Food[]>('/api/foods'),
	getFood: (id: number) => request<Food>(`/api/foods/${id}`),
	createFood: (food: FoodCreate) =>
		request<Food>('/api/foods', { method: 'POST', body: JSON.stringify(food) }),
	scoreFood: (id: number, method: 'diaas' | 'pdcaas') =>
		request<Score>(`/api/foods/${id}/score?method=${method}`)
};
