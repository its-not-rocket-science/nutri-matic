import { auth } from './auth.svelte';
import type { Food, FoodCreate, NutrientAmount, Score, TokenResponse, User } from './types';

const API_URL = import.meta.env.VITE_API_URL;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`;

	const res = await fetch(`${API_URL}${path}`, {
		headers,
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
		request<Score>(`/api/foods/${id}/score?method=${method}`),
	getNutrients: (id: number) => request<NutrientAmount[]>(`/api/foods/${id}/nutrients`),

	register: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
	login: (email: string, password: string) =>
		request<TokenResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
	me: () => request<User>('/api/auth/me')
};
