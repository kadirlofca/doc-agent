import { type UIMessage } from "ai";
import { cookies } from "next/headers";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function POST(req: Request) {
  const body = await req.json();
  const {
    messages,
    docIds,
    conversationId,
  }: {
    messages: UIMessage[];
    docIds?: string[];
    conversationId?: string;
  } = body;

  // Convert UIMessages to simple role/content pairs for our backend
  const simpleMessages = messages.map((m) => ({
    role: m.role,
    content:
      m.parts
        ?.filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("\n") || "",
  }));

  // Read the user ID cookie set by our middleware and forward it
  const cookieStore = await cookies();
  const userId = cookieStore.get("pageindex_user_id")?.value;
  const cookieHeader = userId ? `pageindex_user_id=${userId}` : "";

  const backendRes = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Cookie: cookieHeader,
    },
    body: JSON.stringify({
      messages: simpleMessages,
      doc_ids: docIds || [],
      conversation_id: conversationId || null,
    }),
  });

  if (!backendRes.ok) {
    const error = await backendRes.json().catch(() => ({
      detail: "Backend error",
    }));
    return new Response(JSON.stringify({ error: error.detail }), {
      status: backendRes.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  const result = await backendRes.json();
  const content = result.content || "";

  // Return as AI SDK v6 UIMessageStream format (SSE with JSON chunks)
  // Each chunk needs an `id` to identify the text part
  const partId = crypto.randomUUID();
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "text-start", id: partId })}\n\n`));
      controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "text-delta", id: partId, delta: content })}\n\n`));
      controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "text-end", id: partId })}\n\n`));
      controller.enqueue(encoder.encode("data: [DONE]\n\n"));
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "x-vercel-ai-ui-message-stream": "v1",
      "x-accel-buffering": "no",
    },
  });
}
