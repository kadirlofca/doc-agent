"""
rag.py — RAG pipeline: search document trees, collect context, generate answers.
"""
import asyncio
import json
import re
from typing import List, Dict, Any

from pageindex.llm.base import Message


def _strip_text(node):
    """Remove 'text' fields from tree nodes for lighter search prompts."""
    if isinstance(node, list):
        return [_strip_text(item) for item in node]
    if not isinstance(node, dict):
        return node
    n = {k: v for k, v in node.items() if k != "text"}
    if "nodes" in n:
        n["nodes"] = [_strip_text(c) for c in n["nodes"]]
    return n


async def search_nodes(tree: dict, query: str, provider) -> list:
    """Ask the LLM to pick the most relevant node IDs from a document tree."""
    structure = tree.get("structure", tree) if isinstance(tree, dict) else tree
    tree_lite = _strip_text(structure)
    prompt = (
        "You are a document search assistant.\n"
        "Given the document tree and user question, return ONLY a JSON array "
        "of the most relevant node_id strings (max 5).\n"
        'Example: ["1", "1.2", "3"]\n\n'
        f"Question: {query}\n\n"
        f"Document tree:\n{json.dumps(tree_lite, indent=2)}"
    )
    resp = await provider.complete([Message(role="user", content=prompt)])
    raw = resp.content or "[]"
    try:
        from pageindex.utils import parse_json_robust
        ids = parse_json_robust(raw)
        if isinstance(ids, list):
            return [str(i) for i in ids]
    except Exception:
        pass
    return re.findall(r'"([^"]+)"', raw)[:5]


def collect_node_text(tree: dict, node_ids: list, page_list: list) -> str:
    """Walk the tree and concatenate page text for matching nodes."""
    chunks = []

    def walk(node):
        if not isinstance(node, dict):
            return
        nid = str(node.get("node_id", ""))
        if not node_ids or nid in node_ids:
            start = node.get("start_index", 1)
            end = node.get("end_index", start)
            text = "\n".join(p[0] for p in page_list[start - 1: end])
            chunks.append(f"[{node.get('title', 'Section')}]\n{text}")
        for child in node.get("nodes", []):
            walk(child)

    root = tree.get("structure", tree) if isinstance(tree, dict) else tree
    if isinstance(root, list):
        for n in root:
            walk(n)
    elif isinstance(root, dict):
        walk(root)

    return "\n\n".join(chunks)[:12_000]


async def generate_answer(context: str, query: str, history: list, provider) -> str:
    """Generate an answer from document context using chat history."""
    messages = [
        Message(
            role="system",
            content=(
                "You are a document Q&A assistant. Answer questions using only the "
                "document context provided. Be concise and accurate. If the context "
                "doesn't contain the answer, say so. When referencing information, "
                "mention which document section it came from."
            ),
        ),
    ]
    for h in history[-6:]:
        messages.append(Message(role=h["role"], content=h["content"]))
    messages.append(Message(
        role="user",
        content=f"Question: {query}\n\nDocument context:\n{context}",
    ))
    resp = await provider.complete(messages)
    return resp.content or "No answer generated."


async def run_rag_multi(query: str, doc_data_list: list, provider, history: list) -> str:
    """Run RAG across multiple documents: search in parallel, then generate answer."""
    all_context_parts = []

    search_tasks = [search_nodes(d["tree"], query, provider) for d in doc_data_list]
    all_node_ids = await asyncio.gather(*search_tasks)

    for doc_data, node_ids in zip(doc_data_list, all_node_ids):
        text = collect_node_text(doc_data["tree"], node_ids, doc_data["pages"])
        if text.strip():
            all_context_parts.append(f"[Document: {doc_data['name']}]\n{text}")

    if not all_context_parts:
        first = doc_data_list[0]
        fallback = "\n".join(p[0] for p in first["pages"][:5])
        all_context_parts.append(f"[Document: {first['name']}]\n{fallback}")

    merged = "\n\n---\n\n".join(all_context_parts)
    if len(merged) > 15_000:
        merged = merged[:15_000] + "\n...(truncated)"

    return await generate_answer(merged, query, history, provider)
