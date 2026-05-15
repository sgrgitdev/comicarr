import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { WantedIssue, UpcomingIssue, PaginationMeta } from "@/types";

interface WantedResponse {
  issues: WantedIssue[];
  pagination: PaginationMeta;
}

// Query Hooks
export function useUpcoming(
  includeDownloaded = false,
): UseQueryResult<UpcomingIssue[]> {
  return useQuery({
    queryKey: ["upcoming", includeDownloaded],
    queryFn: () =>
      apiRequest<UpcomingIssue[]>(
        "GET",
        `/api/upcoming${includeDownloaded ? "?include_downloaded_issues=true" : ""}`,
      ),
    staleTime: 2 * 60 * 1000, // 2 minutes (more frequent than series)
  });
}

export function useWanted(
  limit = 50,
  offset = 0,
  search = "",
): UseQueryResult<WantedResponse> {
  return useQuery({
    queryKey: ["wanted", limit, offset, search],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      if (search.trim()) params.set("q", search.trim());
      return apiRequest<WantedResponse>("GET", `/api/wanted?${params}`);
    },
    staleTime: 2 * 60 * 1000,
  });
}

// Mutation Hooks
export function useForceSearch(): UseMutationResult<unknown, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest("POST", "/api/search/force"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["search", "queue"] });
    },
  });
}

export function useSearchIssues(): UseMutationResult<unknown, Error, string[]> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (issueIds: string[]) =>
      apiRequest("POST", "/api/search/issues", { ids: issueIds }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["search", "queue"] });
    },
  });
}

export function useBulkQueueIssues(): UseMutationResult<void, Error, string[]> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds: string[]) => {
      await apiRequest("POST", "/api/series/issues/bulk-queue", {
        ids: issueIds,
        search: false,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

export function useBulkUnqueueIssues(): UseMutationResult<
  void,
  Error,
  string[]
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds: string[]) => {
      await apiRequest("POST", "/api/series/issues/bulk-unqueue", {
        ids: issueIds,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}
