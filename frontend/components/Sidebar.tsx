"use client";

import { useEffect, useState } from "react";
import { ProviderConfig } from "./ProviderConfig";
import { FileUpload } from "./FileUpload";
import { DocumentList } from "./DocumentList";
import { ConversationHistory } from "./ConversationHistory";
import { getHealth } from "@/lib/api";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarRail,
  SidebarSeparator,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { FileTextIcon } from "lucide-react";

interface AppSidebarProps extends React.ComponentProps<typeof Sidebar> {
  activeDocIds: string[];
  onToggleDoc: (docId: string) => void;
  onProviderConnected: () => void;
  refreshTrigger: number;
  onDocumentsUploaded: () => void;
  activeConversationId: string | null;
  onSelectConversation: (convId: string) => void;
  onNewConversation: () => void;
}

export function AppSidebar({
  activeDocIds,
  onToggleDoc,
  onProviderConnected,
  refreshTrigger,
  onDocumentsUploaded,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
  ...props
}: AppSidebarProps) {
  const [supabaseStatus, setSupabaseStatus] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then((h) => setSupabaseStatus(h.supabase))
      .catch((e) => {
        console.error("Failed to fetch health:", e);
        setSupabaseStatus("unreachable");
      });
  }, []);

  return (
    <Sidebar {...props}>
      <SidebarHeader className="border-b">
        <div className="flex items-center justify-between">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <FileTextIcon className="size-4" />
                </div>
                <div className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold">Doc Agent</span>
                  <span className="text-[11px] text-muted-foreground">Document Q&A</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
          <SidebarTrigger />
        </div>
      </SidebarHeader>

      <SidebarContent className="px-1">
        <ProviderConfig onConnected={onProviderConnected} />
        <SidebarSeparator />
        <FileUpload onUploadComplete={onDocumentsUploaded} />
        <SidebarSeparator />
        <DocumentList
          activeDocIds={activeDocIds}
          onToggleDoc={onToggleDoc}
          refreshTrigger={refreshTrigger}
        />
        <SidebarSeparator />
        <ConversationHistory
          activeConversationId={activeConversationId}
          onSelectConversation={onSelectConversation}
          onNewConversation={onNewConversation}
        />
      </SidebarContent>

      <SidebarFooter className="border-t">
        {supabaseStatus && (
          <div className="flex items-center gap-1.5 px-2">
            <span
              className={`inline-block size-2 rounded-full ${
                supabaseStatus === "connected"
                  ? "bg-green-500"
                  : "bg-red-500"
              }`}
            />
            <span className="text-[10px] text-muted-foreground">
              Supabase {supabaseStatus}
            </span>
          </div>
        )}
        <p className="px-2 text-[10px] text-muted-foreground">
          Powered by Doc Agent
        </p>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
