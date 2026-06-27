import { api } from "@/lib/api";
import type { ResearchReport } from "@/types";

export async function getResearchReports(): Promise<ResearchReport[]> {
  return api.get<{ items: ResearchReport[] }>("/research").then(r => r.items);
}

export async function getResearchReport(id: string): Promise<ResearchReport> {
  return api.get(`/research/${id}`);
}

export async function runResearch(payload: { query: string; max_steps?: number }): Promise<ResearchReport> {
  return api.post("/research/run", payload);
}
