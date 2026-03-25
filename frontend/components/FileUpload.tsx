"use client";

import { useRef, useState } from "react";
import { uploadDocuments, subscribeToIndexingProgress } from "@/lib/api";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarGroupAction,
} from "@/components/ui/sidebar";
import { UploadIcon } from "lucide-react";

interface FileUploadProps {
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

export function FileUpload({ onUploadComplete }: FileUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [indexingStates, setIndexingStates] = useState<IndexingState[]>([]);
  const [error, setError] = useState("");

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;

    setUploading(true);
    setError("");

    try {
      const result = await uploadDocuments(Array.from(fileList));

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
    <SidebarGroup className="p-0">
      <SidebarGroupLabel className="px-2">Upload</SidebarGroupLabel>
      <SidebarGroupAction
        onClick={() => fileInputRef.current?.click()}
        title="Upload PDF"
      >
        <UploadIcon className="size-4" />
      </SidebarGroupAction>
      <SidebarGroupContent className="px-2">
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
            className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-sidebar-border px-3 py-4 text-xs text-muted-foreground transition-colors hover:border-sidebar-accent-foreground hover:bg-sidebar-accent"
          >
            <UploadIcon className="size-4" />
            {uploading ? "Uploading..." : "Drop PDFs here or click to browse"}
          </button>
        )}

        {error && (
          <p className="rounded-md bg-destructive/10 p-2 text-[11px] text-destructive">{error}</p>
        )}

        {indexingStates.length > 0 && (
          <div className="space-y-2">
            {indexingStates.map((state) => (
              <div key={state.docId} className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="max-w-[140px] truncate text-[11px]">{state.name}</span>
                  <span className={`text-[11px] font-medium ${
                    state.status === "done" ? "text-secondary" :
                    state.status === "error" ? "text-destructive" :
                    "text-muted-foreground"
                  }`}>
                    {state.status === "done" ? "Done" :
                     state.status === "error" ? "Failed" :
                     `${state.percentage}%`}
                  </span>
                </div>
                <div className="h-1 w-full overflow-hidden rounded-full bg-sidebar-accent">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      state.status === "error" ? "bg-destructive" :
                      state.status === "done" ? "bg-secondary" :
                      "bg-sidebar-primary"
                    }`}
                    style={{ width: `${Math.min(state.percentage, 100)}%` }}
                  />
                </div>
                {state.status === "indexing" && (
                  <p className="text-[10px] text-muted-foreground">{state.step}</p>
                )}
                {state.error && (
                  <p className="text-[10px] text-destructive">{state.error}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
