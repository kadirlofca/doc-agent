"use client";

import { useEffect, useState } from "react";
import { getProviders, connectProvider } from "@/lib/api";
import type { Provider } from "@/lib/types";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { ChevronRightIcon, CheckCircle2Icon, ZapIcon } from "lucide-react";

interface ProviderConfigProps {
  onConnected: () => void;
}

export function ProviderConfig({ onConnected }: ProviderConfigProps) {
  const [providers, setProviders] = useState<Record<string, Provider>>({});
  const [selectedProvider, setSelectedProvider] = useState("gemini");
  const [selectedModel, setSelectedModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<{
    type: "idle" | "loading" | "success" | "error";
    message?: string;
  }>({ type: "idle" });

  useEffect(() => {
    getProviders()
      .then((p) => {
        setProviders(p);
        const first = Object.keys(p)[0];
        if (first) {
          setSelectedProvider(first);
          setSelectedModel(p[first].models[0] || "");
        }
      })
      .catch((e) => console.error("Failed to load providers:", e));
  }, []);

  useEffect(() => {
    const p = providers[selectedProvider];
    if (p) setSelectedModel(p.models[0] || "");
  }, [selectedProvider, providers]);

  const handleConnect = async () => {
    setStatus({ type: "loading" });
    try {
      const result = await connectProvider(selectedProvider, selectedModel, apiKey);
      setStatus({ type: "success", message: `${result.label} / ${result.model}` });
      onConnected();
    } catch (e) {
      setStatus({ type: "error", message: (e as Error).message });
    }
  };

  const currentProvider = providers[selectedProvider];

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="group/collapsible">
      <SidebarGroup className="p-0">
        <SidebarGroupLabel asChild>
          <CollapsibleTrigger className="flex w-full items-center gap-2 px-2">
            <ZapIcon className="size-4" />
            <span className="flex-1 text-left">
              {status.type === "success" ? status.message : "Provider"}
            </span>
            {status.type === "success" && (
              <CheckCircle2Icon className="size-3.5 text-secondary" />
            )}
            <ChevronRightIcon className="size-4 transition-transform group-data-[state=open]/collapsible:rotate-90" />
          </CollapsibleTrigger>
        </SidebarGroupLabel>
        <CollapsibleContent>
          <SidebarGroupContent className="space-y-3 px-2 pb-2">
            <select
              className="w-full rounded-md border bg-background px-2.5 py-1.5 text-xs"
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
            >
              {Object.entries(providers).map(([key, p]) => (
                <option key={key} value={key}>
                  {p.label} {p.free ? "(free)" : ""}
                </option>
              ))}
            </select>

            <select
              className="w-full rounded-md border bg-background px-2.5 py-1.5 text-xs"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              {currentProvider?.models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>

            <Input
              type="password"
              placeholder={currentProvider?.key_hint || "API key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="h-8 text-xs"
            />

            <Button
              onClick={handleConnect}
              className="w-full"
              size="sm"
              disabled={status.type === "loading"}
            >
              {status.type === "loading" ? "Connecting..." : "Connect"}
            </Button>

            {status.type === "error" && (
              <p className="text-[11px] text-destructive">{status.message}</p>
            )}
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}
