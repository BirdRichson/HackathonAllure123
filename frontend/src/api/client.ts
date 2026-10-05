import type { Health, Plant, Targets } from "../types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  health: () => getJson<Health>("/api/health"),
  plant: () => getJson<Plant>("/api/plant"),
  targets: () => getJson<Targets>("/api/targets"),
};
