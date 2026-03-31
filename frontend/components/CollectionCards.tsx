"use client";

import { useEffect, useState } from "react";
import { getCollections } from "@/lib/api";
import type { Collection } from "@/lib/types";
import { Loader2Icon, MonitorIcon, ServerIcon, FileTextIcon, CheckCircleIcon } from "lucide-react";

const COLLECTION_ICONS: Record<string, React.ReactNode> = {
  curam_web_client: <MonitorIcon className="size-8" />,
  curam_web_server: <ServerIcon className="size-8" />,
  user_uploads: <FileTextIcon className="size-8" />,
};

interface CollectionCardsProps {
  onSelectCollection: (collectionId: string) => void;
  activeDocIds?: string[];
}

export function CollectionCards({ onSelectCollection, activeDocIds = [] }: CollectionCardsProps) {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCollections()
      .then(setCollections)
      .catch((e) => console.error("Failed to load collections:", e))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (collections.length === 0) {
    return (
      <div className="py-20 text-center text-muted-foreground">
        <p>No collections available.</p>
        <p className="mt-1 text-sm">Run the database migration to set up collections.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      <div className="mb-8 text-center">
        <h2 className="text-2xl font-semibold tracking-tight">Document Collections</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {activeDocIds.length > 0
            ? "Shared collections are auto-selected. Click a collection to manage documents."
            : "Select a collection to browse documents and ask questions"}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {collections.map((coll) => {
          const isAutoSelected = coll.is_global && coll.doc_count > 0 && activeDocIds.length > 0;
          return (
            <button
              key={coll.id}
              onClick={() => onSelectCollection(coll.id)}
              className={`group flex flex-col items-start gap-3 rounded-xl border p-6 text-left transition-all hover:shadow-md ${
                isAutoSelected
                  ? "border-primary/50 bg-primary/5 hover:border-primary"
                  : "bg-card hover:border-primary/50"
              }`}
            >
              <div className="flex w-full items-center justify-between">
                <div className={`rounded-lg p-2.5 transition-colors ${
                  isAutoSelected
                    ? "bg-primary/10 text-primary"
                    : "bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary"
                }`}>
                  {COLLECTION_ICONS[coll.id] ?? <FileTextIcon className="size-8" />}
                </div>
                {coll.doc_count > 0 && (
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                    isAutoSelected
                      ? "bg-primary/10 text-primary"
                      : "bg-muted text-muted-foreground"
                  }`}>
                    {coll.doc_count} doc{coll.doc_count !== 1 ? "s" : ""}
                  </span>
                )}
              </div>

              <div>
                <h3 className="font-semibold">{coll.name}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{coll.description}</p>
              </div>

              {isAutoSelected ? (
                <span className="flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-[10px] font-medium text-green-600 dark:bg-green-950 dark:text-green-400">
                  <CheckCircleIcon className="size-3" />
                  Auto-selected
                </span>
              ) : coll.is_global ? (
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-600 dark:bg-blue-950 dark:text-blue-400">
                  Shared
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
