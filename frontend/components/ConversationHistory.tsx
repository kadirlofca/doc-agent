"use client";

import { useEffect, useState } from "react";
import { getConversations, deleteConversation } from "@/lib/api";
import type { Conversation } from "@/lib/types";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarMenuAction,
} from "@/components/ui/sidebar";
import { PlusIcon, Trash2Icon, MessageSquareIcon } from "lucide-react";

interface ConversationHistoryProps {
  activeConversationId: string | null;
  onSelectConversation: (convId: string) => void;
  onNewConversation: () => void;
}

export function ConversationHistory({
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: ConversationHistoryProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);

  useEffect(() => {
    getConversations()
      .then(setConversations)
      .catch((e) => console.error("Failed to load conversations:", e));
  }, []);

  const handleDelete = async (e: React.MouseEvent, convId: string) => {
    e.stopPropagation();
    try {
      await deleteConversation(convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConversationId === convId) onNewConversation();
    } catch (e) {
      console.error("Failed to delete conversation:", e);
    }
  };

  return (
    <SidebarGroup className="p-0">
      <SidebarGroupLabel className="px-2">History</SidebarGroupLabel>
      <SidebarGroupAction onClick={onNewConversation} title="New chat">
        <PlusIcon className="size-4" />
      </SidebarGroupAction>
      <SidebarGroupContent>
        {conversations.length === 0 && (
          <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">
            No conversations yet
          </p>
        )}
        <SidebarMenu>
          {conversations.slice(0, 10).map((conv) => (
            <SidebarMenuItem key={conv.id}>
              <SidebarMenuButton
                isActive={activeConversationId === conv.id}
                onClick={() => onSelectConversation(conv.id)}
                tooltip={conv.title}
              >
                <MessageSquareIcon className="size-4" />
                <span className="truncate">{conv.title}</span>
              </SidebarMenuButton>
              <SidebarMenuAction
                showOnHover
                onClick={(e) => handleDelete(e, conv.id)}
              >
                <Trash2Icon className="size-4" />
              </SidebarMenuAction>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
