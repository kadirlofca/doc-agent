"use client";

import { useState, useCallback } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useChatRuntime, AssistantChatTransport } from "@assistant-ui/react-ai-sdk";
import { Thread } from "@/components/assistant-ui/thread";
import { AppSidebar } from "@/components/Sidebar";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";

export const Assistant = () => {
  const [activeDocIds, setActiveDocIds] = useState<string[]>([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);

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

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <SidebarProvider defaultOpen={false}>
        <div className="flex h-dvh w-full pr-0.5">
          <AppSidebar
            side="right"
            activeDocIds={activeDocIds}
            onToggleDoc={handleToggleDoc}
            onProviderConnected={handleProviderConnected}
            refreshTrigger={refreshTrigger}
            onDocumentsUploaded={handleDocumentsUploaded}
            activeConversationId={activeConversationId}
            onSelectConversation={handleSelectConversation}
            onNewConversation={handleNewConversation}
          />
          <SidebarInset>
            <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
              <h1 className="text-sm font-medium">
                {activeDocIds.length > 0
                  ? `${activeDocIds.length} document${activeDocIds.length > 1 ? "s" : ""} selected`
                  : "Doc Agent"}
              </h1>
              <div className="ml-auto flex items-center gap-2">
                <Separator orientation="vertical" className="h-4" />
                <SidebarTrigger />
              </div>
            </header>
            <div className="flex-1 overflow-hidden">
              <Thread />
            </div>
          </SidebarInset>
        </div>
      </SidebarProvider>
    </AssistantRuntimeProvider>
  );
};
