import type { UseQueryResult } from "@tanstack/react-query";
import { ApiClientError } from "@/lib/api";
import { useDemoContext } from "@/providers/DemoProvider";

type QueryHook<T> = () => UseQueryResult<T, Error>;

const DEMO_FALLBACK_ENABLED = import.meta.env.VITE_ENABLE_DEMO_FALLBACK === "true";

function isFallbackError(error: unknown): boolean {
  if (!error) return false;
  if (error instanceof ApiClientError) {
    return error.status >= 500;
  }
  if (error instanceof TypeError && error.message === "Failed to fetch") {
    return true;
  }
  return false;
}

function devLog(workspace: string, error: unknown) {
  if (typeof process !== "undefined" && process.env?.NODE_ENV === "production") return;
  console.warn(
    `[RegIntel Demo] Fallback activated for "${workspace}" - backend unavailable.`,
    error instanceof Error ? error.message : error,
  );
}

export function useDemoQuery<T>(
  workspace: string,
  demoData: T,
  queryHook: QueryHook<T>,
): UseQueryResult<T, Error> {
  const { add, remove } = useDemoContext();
  const query = queryHook();

  const shouldFallback =
    DEMO_FALLBACK_ENABLED &&
    query.isError &&
    isFallbackError(query.error) &&
    !query.isSuccess;

  if (shouldFallback) {
    if (workspace) add(workspace);
    devLog(workspace, query.error);
    return {
      ...query,
      data: demoData,
      isError: false,
      isLoading: false,
      isSuccess: true,
      isPlaceholderData: true,
      isFetched: true,
      isFetchedAfterMount: true,
      status: "success" as const,
      fetchStatus: "idle" as const,
      error: null,
      errorUpdatedAt: 0,
    } as unknown as UseQueryResult<T, Error>;
  }

  if (query.isSuccess && query.data && workspace) {
    remove(workspace);
  }

  return query;
}
