"use client";

import { useRef, useState } from "react";
import { uploadDocuments, subscribeToIndexingProgress } from "@/lib/api";
import { UploadIcon, Loader2Icon, CheckCircleIcon, XCircleIcon } from "lucide-react";

interface FileUploadAreaProps {
  collectionId?: string;
  onUploadComplete: () => void;
}

interface IndexingState {
  docId: string;
  name: string;
  percentage: number;
  step: string;
  status: "indexing" | "done" | "error";
  error?: string;
}

export function FileUploadArea({ collectionId, onUploadComplete }: FileUploadAreaProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [indexingStates, setIndexingStates] = useState<IndexingState[]>([]);
  const [error, setError] = useState("");

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;

    setUploading(true);
    setError("");

    try {
      const result = await uploadDocuments(Array.from(fileList), collectionId);

      const states: IndexingState[] = result.documents.map((d) => ({
        docId: d.doc_id,
        name: d.name,
        percentage: 0,
        step: "Starting...",
        status: "indexing" as const,
      }));
      setIndexingStates(states);

      for (const doc of result.documents) {
        subscribeToIndexingProgress(
          doc.doc_id,
          (progress) => {
            setIndexingStates((prev) =>
              prev.map((s) =>
                s.docId === doc.doc_id
                  ? { ...s, percentage: progress.percentage, step: progress.step }
                  : s,
              ),
            );
          },
          () => {
            setIndexingStates((prev) =>
              prev.map((s) =>
                s.docId === doc.doc_id
                  ? { ...s, status: "done", percentage: 100, step: "Complete" }
                  : s,
              ),
            );
            onUploadComplete();
          },
          (err) => {
            setIndexingStates((prev) =>
              prev.map((s) =>
                s.docId === doc.doc_id
                  ? { ...s, status: "error", error: err }
                  : s,
              ),
            );
          },
        );
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const hasActive = indexingStates.some((s) => s.status === "indexing");

  return (
    <div className="space-y-3">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        multiple
        className="hidden"
        disabled={uploading || hasActive}
        onChange={(e) => handleFiles(e.target.files)}
      />

      {!hasActive && indexingStates.length === 0 && !error && (
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:bg-muted/50"
        >
          <UploadIcon className="size-5" />
          {uploading ? "Uploading..." : "Drop PDFs here or click to browse"}
        </button>
      )}

      {error && (
        <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
      )}

      {indexingStates.length > 0 && (
        <div className="space-y-3">
          {indexingStates.map((state) => (
            <div key={state.docId} className="rounded-lg border p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {state.status === "done" ? (
                    <CheckCircleIcon className="size-4 text-green-500" />
                  ) : state.status === "error" ? (
                    <XCircleIcon className="size-4 text-destructive" />
                  ) : (
                    <Loader2Icon className="size-4 animate-spin" />
                  )}
                  <span className="max-w-[200px] truncate text-sm font-medium">{state.name}</span>
                </div>
                <span
                  className={`text-xs font-medium ${
                    state.status === "done"
                      ? "text-green-500"
                      : state.status === "error"
                        ? "text-destructive"
                        : "text-muted-foreground"
                  }`}
                >
                  {state.status === "done"
                    ? "Done"
                    : state.status === "error"
                      ? "Failed"
                      : `${state.percentage}%`}
                </span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full transition-all duration-300 ${
                    state.status === "error"
                      ? "bg-destructive"
                      : state.status === "done"
                        ? "bg-green-500"
                        : "bg-primary"
                  }`}
                  style={{ width: `${Math.min(state.percentage, 100)}%` }}
                />
              </div>
              {state.status === "indexing" && (
                <p className="mt-1 text-[11px] text-muted-foreground">{state.step}</p>
              )}
              {state.error && (
                <p className="mt-1 text-[11px] text-destructive">{state.error}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
