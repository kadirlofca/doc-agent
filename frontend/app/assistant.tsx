"use client";

import { useState, useCallback, useEffect } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useChatRuntime, AssistantChatTransport } from "@assistant-ui/react-ai-sdk";
import { Thread } from "@/components/assistant-ui/thread";
import { CollectionCards } from "@/components/CollectionCards";
import { CollectionView } from "@/components/CollectionView";
import { AppSidebar } from "@/components/Sidebar";
import { useAuth } from "@/components/AuthProvider";
import { getDocuments } from "@/lib/api";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";

export const Assistant = () => {
  const { user, loading } = useAuth();
  const [activeDocIds, setActiveDocIds] = useState<string[]>([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeCollection, setActiveCollection] = useState<string | null>(null);
  const [initialLoadDone, setInitialLoadDone] = useState(false);

  // Auto-select global collection docs (Web Client + Web Server) on first load
  useEffect(() => {
    if (loading || !user) return;
    getDocuments()
      .then((docs) => {
        const globalIndexedIds = docs
          .filter((d) => d.status === "indexed" && d.is_global)
          .map((d) => d.id);
        if (globalIndexedIds.length > 0) {
          setActiveDocIds(globalIndexedIds);
        }
      })
      .catch((e) => console.error("Failed to auto-select docs:", e))
      .finally(() => setInitialLoadDone(true));
  }, [loading, user]);

  const runtime = useChatRuntime({
    transport: new AssistantChatTransport({
      api: "/api/chat",
      body: {
        docIds: activeDocIds,
        conversationId: activeConversationId,
      },
    }),
  });

  const handleToggleDoc = useCallback((docId: string) => {
    setActiveDocIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId],
    );
    setActiveConversationId(null);
  }, []);

  const handleProviderConnected = useCallback(() => {}, []);

  const handleDocumentsUploaded = useCallback(() => {
    setRefreshTrigger((t) => t + 1);
  }, []);

  const handleSelectConversation = useCallback((convId: string) => {
    setActiveConversationId(convId);
  }, []);

  const handleNewConversation = useCallback(() => {
    setActiveConversationId(null);
  }, []);

  const handleBackToCollections = useCallback(() => {
    setActiveCollection(null);
  }, []);

  // Determine what to show in the main area
  // Collection cards are the home view — always shown when no specific collection is open
  const showCollectionCards = activeCollection === null;
  const showCollectionView = activeCollection !== null;
  const showChat = activeDocIds.length > 0;

  if (loading || !initialLoadDone) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-950">
        <div className="text-zinc-400">Loading...</div>
      </div>
    );
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <SidebarProvider defaultOpen={false}>
        <div className="flex h-dvh w-full pr-0.5">
          <AppSidebar
            side="right"
            activeDocIds={activeDocIds}
            onToggleDoc={handleToggleDoc}
            onSelectAll={setActiveDocIds}
            onProviderConnected={handleProviderConnected}
            refreshTrigger={refreshTrigger}
            onDocumentsUploaded={handleDocumentsUploaded}
            activeConversationId={activeConversationId}
            onSelectConversation={handleSelectConversation}
            onNewConversation={handleNewConversation}
            onBrowseCollections={handleBackToCollections}
          />
          <SidebarInset>
            <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
              <h1 className="text-sm font-medium">Doc Agent</h1>
              {activeDocIds.length > 0 && (
                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                  {activeDocIds.length} doc{activeDocIds.length !== 1 ? "s" : ""} selected
                </span>
              )}
              <div className="ml-auto flex items-center gap-2">
                <Separator orientation="vertical" className="h-4" />
                <SidebarTrigger />
              </div>
            </header>

            <div className="flex flex-1 flex-col overflow-y-auto">
              {showCollectionCards && (
                <CollectionCards onSelectCollection={setActiveCollection} activeDocIds={activeDocIds} />
              )}

              {showCollectionView && (
                <CollectionView
                  collectionId={activeCollection}
                  activeDocIds={activeDocIds}
                  onToggleDoc={handleToggleDoc}
                  onBack={handleBackToCollections}
                  onDocumentsUploaded={handleDocumentsUploaded}
                  userRole={user?.role}
                />
              )}

              {showChat && !showCollectionView && (
                <div className="flex-1">
                  <Thread />
                </div>
              )}
            </div>
          </SidebarInset>
        </div>
      </SidebarProvider>
    </AssistantRuntimeProvider>
  );
};
