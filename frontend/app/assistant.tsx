"use client";

import { useState, useCallback, useEffect } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useChatRuntime, AssistantChatTransport } from "@assistant-ui/react-ai-sdk";
import { Thread } from "@/components/assistant-ui/thread";
import { CollectionCards } from "@/components/CollectionCards";
import { CollectionView } from "@/components/CollectionView";
import { AppSidebar } from "@/components/Sidebar";
import { useAuth } from "@/components/AuthProvider";
import { getCollectionDocuments } from "@/lib/api";
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

  const GLOBAL_COLLECTIONS = ["curam_web_client", "curam_web_server"];

  // When a collection is opened, auto-select all its indexed docs if global
  useEffect(() => {
    if (!activeCollection) return;
    if (!GLOBAL_COLLECTIONS.includes(activeCollection)) return;

    getCollectionDocuments(activeCollection)
      .then((docs) => {
        const indexedIds = docs
          .filter((d) => d.status === "indexed")
          .map((d) => d.id);
        if (indexedIds.length > 0) {
          setActiveDocIds(indexedIds);
        }
      })
      .catch((e) => console.error("Failed to auto-select collection docs:", e));
  }, [activeCollection]);

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
    setActiveDocIds([]);
    setActiveConversationId(null);
  }, []);

  // Home = cards only; collection open = doc list + chat
  const isHome = activeCollection === null;
  const showChat = activeDocIds.length > 0;

  if (loading) {
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

            {isHome ? (
              <div className="flex-1 overflow-y-auto">
                <CollectionCards onSelectCollection={setActiveCollection} />
              </div>
            ) : (
              <div className="flex flex-1 overflow-hidden">
                {/* Left panel: collection doc list */}
                <div className="w-80 shrink-0 overflow-y-auto border-r">
                  <CollectionView
                    collectionId={activeCollection}
                    activeDocIds={activeDocIds}
                    onToggleDoc={handleToggleDoc}
                    onBack={handleBackToCollections}
                    onDocumentsUploaded={handleDocumentsUploaded}
                    userRole={user?.role}
                  />
                </div>

                {/* Right panel: chat */}
                <div className="flex-1">
                  {showChat ? (
                    <Thread />
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                      Select documents to start chatting
                    </div>
                  )}
                </div>
              </div>
            )}
          </SidebarInset>
        </div>
      </SidebarProvider>
    </AssistantRuntimeProvider>
  );
};
