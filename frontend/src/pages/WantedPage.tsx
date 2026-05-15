import { useState } from "react";
import { Search, RefreshCw } from "lucide-react";
import {
  useWanted,
  useForceSearch,
  useSearchIssues,
  useBulkUnqueueIssues,
} from "@/hooks/useQueue";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import WantedTable from "@/components/queue/WantedTable";
import BulkActionBar from "@/components/queue/BulkActionBar";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import PageHeader from "@/components/layout/PageHeader";
import FilterField from "@/components/ui/FilterField";

export default function WantedPage() {
  const [page, setPage] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const limit = 50;
  const offset = page * limit;

  const { data, isLoading, error, refetch } = useWanted(
    limit,
    offset,
    searchQuery,
  );
  const issues = data?.issues || [];
  const pagination = data?.pagination;

  const forceSearch = useForceSearch();
  const searchIssues = useSearchIssues();
  const bulkUnqueue = useBulkUnqueueIssues();
  const { addToast } = useToast();

  const handleBulkUnqueue = async () => {
    try {
      await bulkUnqueue.mutateAsync(selectedIds);
      addToast({
        type: "success",
        message: `${selectedIds.length} issue${selectedIds.length !== 1 ? "s" : ""} skipped`,
      });
      setSelectedIds([]);
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to skip issues: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleForceSearch = async () => {
    try {
      const result = (await forceSearch.mutateAsync()) as {
        job_id?: number;
        total_items?: number;
      };
      addToast({
        type: "info",
        message: `Search job ${result.job_id ? `#${result.job_id} ` : ""}queued for ${result.total_items ?? "wanted"} item(s)`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start search: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleSearchSelected = async () => {
    try {
      const result = (await searchIssues.mutateAsync(selectedIds)) as {
        job_id?: number;
        total_items?: number;
      };
      addToast({
        type: "info",
        message: `Search job ${result.job_id ? `#${result.job_id} ` : ""}queued for ${result.total_items ?? selectedIds.length} issue(s)`,
      });
      setSelectedIds([]);
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start selected search: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const total = pagination?.total ?? issues.length;

  return (
    <div className="page-transition">
      <PageHeader
        title="Wanted"
        meta={
          isLoading
            ? "loading…"
            : `${total} issue${total === 1 ? "" : "s"} in queue`
        }
        actions={
          <>
            <button
              type="button"
              onClick={() => refetch()}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-[5px] border font-mono text-[11px] text-muted-foreground"
              style={{ borderColor: "var(--border)" }}
            >
              <RefreshCw
                className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`}
              />
              refresh
            </button>
            <button
              type="button"
              onClick={handleForceSearch}
              disabled={forceSearch.isPending}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] text-[12px] font-semibold disabled:opacity-60"
              style={{
                background: "var(--primary)",
                color: "var(--primary-foreground)",
              }}
            >
              <Search className="w-3.5 h-3.5" />
              Force search
            </button>
          </>
        }
      />

      <div className="px-5 py-2.5 border-b border-border flex items-center gap-3">
        <div className="flex-1 max-w-md">
          <FilterField
            placeholder="Filter wanted issues…"
            aria-label="Filter wanted issues"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(0);
              setSelectedIds([]);
            }}
            shortcut="/"
          />
        </div>
        {searchQuery && (
          <div className="font-mono text-[11px] text-muted-foreground">
            {pagination?.total ?? issues.length} match
            {(pagination?.total ?? issues.length) === 1 ? "" : "es"}
          </div>
        )}
      </div>

      {isLoading && (
        <div className="px-5 py-4 space-y-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      )}

      {error && (
        <div className="px-5 py-4">
          <ErrorDisplay
            error={error}
            title="Unable to load wanted issues"
            onRetry={() => refetch()}
          />
        </div>
      )}

      {!isLoading && !error && (
        <WantedTable
          issues={issues}
          pagination={pagination}
          onNextPage={() => {
            setPage((p) => p + 1);
            setSelectedIds([]);
          }}
          onPrevPage={() => {
            setPage((p) => Math.max(0, p - 1));
            setSelectedIds([]);
          }}
          onSelectionChange={setSelectedIds}
        />
      )}

      <BulkActionBar
        selectedCount={selectedIds.length}
        onSearch={handleSearchSelected}
        onSkip={handleBulkUnqueue}
        onClear={() => setSelectedIds([])}
        isLoading={bulkUnqueue.isPending || searchIssues.isPending}
      />
    </div>
  );
}
