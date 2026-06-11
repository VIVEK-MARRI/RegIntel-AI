import { createContext, useContext, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { getHealth, type HealthStatus } from "@/services/api/healthApi";

interface HealthContextValue {
  status: HealthStatus | undefined;
  isLoading: boolean;
  isError: boolean;
  isHealthy: boolean;
  isDegraded: boolean;
  isUnavailable: boolean;
}

const HealthContext = createContext<HealthContextValue>({
  status: undefined,
  isLoading: true,
  isError: false,
  isHealthy: false,
  isDegraded: false,
  isUnavailable: true,
});

export function HealthProvider({ children }: { children: ReactNode }) {
  const { data: status, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: 2,
    staleTime: 15_000,
  });

  const value: HealthContextValue = {
    status,
    isLoading,
    isError,
    isHealthy: status?.status === "healthy",
    isDegraded: status?.status === "degraded",
    isUnavailable: isError || (!isLoading && !status),
  };

  return (
    <HealthContext.Provider value={value}>
      {children}
    </HealthContext.Provider>
  );
}

export function useHealth(): HealthContextValue {
  return useContext(HealthContext);
}
