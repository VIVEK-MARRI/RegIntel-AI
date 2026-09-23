import { LONG_TIMEOUT_MS, api, encodePathSegment } from "@/lib/api";
import type {
  PaginatedResearchReports,
  ResearchListQuery,
  ResearchReport,
  ResearchRequest,
  ResearchStats,
} from "@/types/api/research";

export async function getResearchStats(): Promise<ResearchStats> {
  return api.get<ResearchStats>("/research/stats");
}

export async function getResearchReports(
  query?: ResearchListQuery
): Promise<ResearchReport[]> {
  const res = await api.get<PaginatedResearchReports>("/research", { query });
  return res.items;
}

export async function getResearchReport(id: string): Promise<ResearchReport> {
  return api.get<ResearchReport>(`/research/${encodePathSegment(id)}`);
}

export async function runResearch(payload: ResearchRequest): Promise<ResearchReport> {
  return api.post<ResearchReport>("/research/run", payload, {
    timeoutMs: LONG_TIMEOUT_MS,
  });
}
