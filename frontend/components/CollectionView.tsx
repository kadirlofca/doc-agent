"use client";

import { useEffect, useState, useCallback } from "react";
import { getCollectionDocuments, getCollections, deleteDocument } from "@/lib/api";
import { FileUploadArea } from "./FileUploadArea";
import type { Collection, Document } from "@/lib/types";
import {
  ArrowLeftIcon,
  CheckIcon,
  FileTextIcon,
  Loader2Icon,
  Trash2Icon,
  XCircleIcon,
} from "lucide-react";

interface CollectionViewProps {
  collectionId: string;
  activeDocIds: string[];
  onToggleDoc: (docId: string) => void;
  onBack: () => void;
  onDocumentsUploaded: () => void;
  userRole?: "admin" | "user";
}

export function CollectionView({
  collectionId,
  activeDocIds,
  onToggleDoc,
  onBack,
  onDocumentsUploaded,
  userRole = "user",
}: CollectionViewProps) {
  const [collection, setCollection] = useState<Collection | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchDocs = useCallback(async () => {
    try {
      const docs = await getCollectionDocuments(collectionId);
      setDocuments(docs);
    } catch (e) {
      console.error("Failed to load collection documents:", e);
    } finally {
      setLoading(false);
    }
  }, [collectionId]);

  useEffect(() => {
    getCollections().then((colls) => {
      const found = colls.find((c) => c.id === collectionId);
      if (found) setCollection(found);
    });
    fetchDocs();
  }, [collectionId, fetchDocs]);

  const handleUploadComplete = useCallback(() => {
    fetchDocs();
    onDocumentsUploaded();
  }, [fetchDocs, onDocumentsUploaded]);

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (e) {
      console.error("Failed to delete document:", e);
    }
  };

  const indexed = documents.filter((d) => d.status === "indexed");
  const other = documents.filter((d) => d.status !== "indexed");
  const selectedCount = activeDocIds.filter((id) => indexed.some((d) => d.id === id)).length;

  // Select / deselect all indexed docs in this collection
  const allSelected = indexed.length > 0 && indexed.every((d) => activeDocIds.includes(d.id));

  return (
    <div className="px-3 py-4">
      {/* Header */}
      <button
        onClick={onBack}
        className="mb-3 flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeftIcon className="size-3.5" />
        Collections
      </button>

      {collection && (
        <div className="mb-4">
          <h2 className="text-sm font-semibold">{collection.name}</h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{collection.description}</p>
        </div>
      )}

      {/* Upload section */}
      {(collectionId === "user_uploads" || userRole === "admin") && (
        <div className="mb-4">
          <FileUploadArea collectionId={collectionId} onUploadComplete={handleUploadComplete} />
        </div>
      )}

      {/* Document list */}
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2Icon className="size-4 animate-spin text-muted-foreground" />
        </div>
      ) : indexed.length === 0 && other.length === 0 ? (
        <div className="rounded-lg border border-dashed py-8 text-center text-xs text-muted-foreground">
          No documents yet. Upload a PDF to get started.
        </div>
      ) : (
        <div className="space-y-1">
          {indexed.length > 0 && (
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {indexed.length} doc{indexed.length !== 1 ? "s" : ""}
                {selectedCount > 0 && ` · ${selectedCount} selected`}
              </p>
              <button
                onClick={() => {
                  if (allSelected) {
                    // Deselect all docs in this collection
                    const collDocIds = new Set(indexed.map((d) => d.id));
                    const remaining = activeDocIds.filter((id) => !collDocIds.has(id));
                    // We need to toggle each one off — use onToggleDoc for each
                    for (const doc of indexed) {
                      if (activeDocIds.includes(doc.id)) {
                        onToggleDoc(doc.id);
                      }
                    }
                  } else {
                    // Select all docs in this collection
                    for (const doc of indexed) {
                      if (!activeDocIds.includes(doc.id)) {
                        onToggleDoc(doc.id);
                      }
                    }
                  }
                }}
                className="text-[10px] text-primary hover:underline"
              >
                {allSelected ? "Deselect all" : "Select all"}
              </button>
            </div>
          )}

          {indexed.map((doc) => {
            const isActive = activeDocIds.includes(doc.id);
            return (
              <div
                key={doc.id}
                className={`flex items-center gap-2 rounded-md border px-3 py-2 transition-colors cursor-pointer ${
                  isActive
                    ? "border-primary/50 bg-primary/5"
                    : "hover:bg-muted/50"
                }`}
                onClick={() => onToggleDoc(doc.id)}
              >
                <div
                  className={`flex size-4 shrink-0 items-center justify-center rounded border transition-colors ${
                    isActive
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-muted-foreground/30"
                  }`}
                >
                  {isActive && <CheckIcon className="size-3" />}
                </div>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium">{doc.name}</p>
                  <p className="text-[10px] text-muted-foreground">
                    {doc.page_count ?? "?"} pg
                    {doc.total_tokens ? ` · ${(doc.total_tokens / 1000).toFixed(0)}k tok` : ""}
                  </p>
                </div>

                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(doc.id);
                  }}
                  className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive [div:hover>&]:opacity-100"
                  title="Delete document"
                >
                  <Trash2Icon className="size-3.5" />
                </button>
              </div>
            );
          })}

          {other.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center gap-2 rounded-md border px-3 py-2 opacity-60"
            >
              {doc.status === "indexing" || doc.status === "uploaded" ? (
                <Loader2Icon className="size-3.5 shrink-0 animate-spin" />
              ) : (
                <XCircleIcon className="size-3.5 shrink-0 text-destructive" />
              )}
              <span className="truncate text-xs">{doc.name}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">{doc.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
