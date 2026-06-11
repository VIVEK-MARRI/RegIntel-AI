import { api } from "@/lib/api";
import type { ResearchReport } from "@/types";

export async function getResearchReports(): Promise<ResearchReport[]> {
  return api.get("/research/reports");
}

export async function getResearchReport(id: string): Promise<ResearchReport> {
  return api.get(`/research/reports/${id}`);
}

export async function runResearch(payload: { query: string; depth?: number }): Promise<ResearchReport> {
  return api.post("/research/run", payload);
}
