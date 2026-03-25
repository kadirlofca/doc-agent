"use client";

import { useEffect, useState, useCallback } from "react";
import { getDocuments, deleteDocument } from "@/lib/api";
import type { Document } from "@/lib/types";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarMenuAction,
} from "@/components/ui/sidebar";
import {
  FileTextIcon,
  Trash2Icon,
  Loader2Icon,
  XCircleIcon,
  CheckIcon,
} from "lucide-react";

interface DocumentListProps {
  activeDocIds: string[];
  onToggleDoc: (docId: string) => void;
  refreshTrigger: number;
}

export function DocumentList({
  activeDocIds,
  onToggleDoc,
  refreshTrigger,
}: DocumentListProps) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchDocs = useCallback(async () => {
    try {
      const docs = await getDocuments();
      setDocuments(docs);
    } catch (e) {
      console.error("Failed to load documents:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs, refreshTrigger]);

  const handleDelete = async (e: React.MouseEvent, docId: string) => {
    e.stopPropagation();
    try {
      await deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (e) {
      console.error("Failed to delete document:", e);
    }
  };

  const indexed = documents.filter((d) => d.status === "indexed");
  const other = documents.filter((d) => d.status !== "indexed");

  return (
    <SidebarGroup className="p-0">
      <SidebarGroupLabel className="px-2">
        Documents
        {activeDocIds.length > 0 && (
          <span className="ml-auto rounded-full bg-sidebar-primary px-1.5 text-[10px] text-sidebar-primary-foreground">
            {activeDocIds.length}
          </span>
        )}
      </SidebarGroupLabel>
      <SidebarGroupContent>
        {loading && (
          <div className="flex items-center gap-2 px-2 py-4 text-xs text-muted-foreground">
            <Loader2Icon className="size-3.5 animate-spin" /> Loading...
          </div>
        )}

        {!loading && indexed.length === 0 && other.length === 0 && (
          <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">
            No documents yet
          </p>
        )}

        <SidebarMenu>
          {indexed.map((doc) => {
            const isActive = activeDocIds.includes(doc.id);
            return (
              <SidebarMenuItem key={doc.id}>
                <SidebarMenuButton
                  isActive={isActive}
                  onClick={() => onToggleDoc(doc.id)}
                  tooltip={doc.name}
                >
                  {isActive ? (
                    <CheckIcon className="size-4 text-primary" />
                  ) : (
                    <FileTextIcon className="size-4" />
                  )}
                  <span className="truncate">{doc.name}</span>
                </SidebarMenuButton>
                <SidebarMenuAction
                  showOnHover
                  onClick={(e) => handleDelete(e, doc.id)}
                >
                  <Trash2Icon className="size-4" />
                </SidebarMenuAction>
              </SidebarMenuItem>
            );
          })}

          {other.map((doc) => (
            <SidebarMenuItem key={doc.id}>
              <SidebarMenuButton disabled className="opacity-60">
                {doc.status === "indexing" || doc.status === "uploaded" ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : (
                  <XCircleIcon className="size-4 text-destructive" />
                )}
                <span className="truncate">{doc.name}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
