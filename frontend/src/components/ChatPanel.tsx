import { ArrowUp, BookOpen, ExternalLink, FileText, Sparkles, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamChat, type Message, type Source } from "../api";
import { cn } from "../utils";
import { ErrorBanner, Modal, Spinner } from "./ui";

const SUGGESTIONS = [
  "Summarize the key points across these files",
  "What are the important dates and deadlines?",
  "List any numbers, budgets or figures mentioned",
];

const PENDING_ID = "__pending__";

type LocalMessage = Message & { streaming?: boolean; failed?: boolean };

export default function ChatPanel({
  projectId,
  conversationId,
  documentIds,
  readyDocCount,
  onConversationCreated,
  onConversationUpdated,
}: {
  projectId: string;
  conversationId?: string;
  documentIds: string[];
  readyDocCount: number;
  onConversationCreated: (id: string) => void;
  onConversationUpdated: () => void;
}) {
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [openSource, setOpenSource] = useState<Source | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const skipLoadFor = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load the conversation when the route changes.
  useEffect(() => {
    setError(null);
    if (!conversationId) {
      abortRef.current?.abort();
      setMessages([]);
      return;
    }
    if (skipLoadFor.current === conversationId) {
      skipLoadFor.current = null; // we just created it and are already streaming into it
      return;
    }
    abortRef.current?.abort();
    let cancelled = false;
    setLoading(true);
    api
      .getConversation(conversationId)
      .then((c) => !cancelled && setMessages(c.messages))
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Auto-scroll while streaming unless the user scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  const patchPending = (fn: (m: LocalMessage) => LocalMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === PENDING_ID ? fn(m) : m)));

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || streaming) return;
    setError(null);
    setInput("");
    stickToBottom.current = true;

    let convId = conversationId;
    try {
      if (!convId) {
        const conv = await api.createConversation(projectId);
        convId = conv.id;
        skipLoadFor.current = conv.id;
        onConversationCreated(conv.id);
      }
    } catch (e) {
      setError((e as Error).message);
      setInput(content);
      return;
    }

    const now = new Date().toISOString();
    setMessages((ms) => [
      ...ms,
      { id: `user-${Date.now()}`, role: "user", content, sources: null, created_at: now },
      { id: PENDING_ID, role: "assistant", content: "", sources: null, created_at: now, streaming: true },
    ]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat(
        convId,
        content,
        documentIds,
        (event) => {
          switch (event.type) {
            case "sources":
              patchPending((m) => ({ ...m, sources: event.sources }));
              break;
            case "token":
              patchPending((m) => ({ ...m, content: m.content + event.content }));
              break;
            case "done":
              patchPending((m) => ({ ...m, id: event.message_id, streaming: false }));
              break;
            case "error":
              setError(event.error);
              patchPending((m) => ({ ...m, streaming: false, failed: true }));
              break;
          }
        },
        controller.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      patchPending((m) => ({ ...m, id: `local-${Date.now()}`, streaming: false }));
      setStreaming(false);
      abortRef.current = null;
      onConversationUpdated();
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(input);
    }
  };

  const empty = !loading && messages.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} onScroll={onScroll} className="scrollbar-thin flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : empty ? (
          <EmptyChat readyDocCount={readyDocCount} onPick={send} />
        ) : (
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm whitespace-pre-wrap text-white shadow-sm">
                    {m.content}
                  </div>
                </div>
              ) : (
                <AssistantMessage key={m.id} message={m} onOpenSource={setOpenSource} />
              ),
            )}
          </div>
        )}
      </div>

      <div className="border-t border-slate-200 bg-white/80 px-4 py-3 backdrop-blur">
        <div className="mx-auto max-w-3xl">
          {error && (
            <div className="mb-2">
              <ErrorBanner message={error} onDismiss={() => setError(null)} />
            </div>
          )}
          <div className="flex items-end gap-2 rounded-2xl bg-white p-2 shadow-sm ring-1 ring-slate-300 focus-within:ring-2 focus-within:ring-indigo-500">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={
                readyDocCount ? "Ask a question about your files…" : "Upload files to start chatting…"
              }
              className="max-h-[200px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-slate-400"
            />
            {streaming ? (
              <button
                onClick={() => abortRef.current?.abort()}
                title="Stop generating"
                className="flex size-9 items-center justify-center rounded-xl bg-slate-800 text-white hover:bg-slate-700"
              >
                <Square className="size-3.5 fill-current" />
              </button>
            ) : (
              <button
                onClick={() => send(input)}
                disabled={!input.trim()}
                title="Send (Enter)"
                className="flex size-9 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-slate-200 disabled:text-slate-400"
              >
                <ArrowUp className="size-4" />
              </button>
            )}
          </div>
          <p className="mt-1.5 text-center text-[11px] text-slate-400">
            {documentIds.length
              ? `Answering from ${documentIds.length} selected file${documentIds.length > 1 ? "s" : ""}`
              : "Answers are generated from your project's files"}{" "}
            · Shift+Enter for a new line
          </p>
        </div>
      </div>

      <SourceModal source={openSource} onClose={() => setOpenSource(null)} />
    </div>
  );
}

function EmptyChat({ readyDocCount, onPick }: { readyDocCount: number; onPick: (q: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-indigo-50">
        <Sparkles className="size-6 text-indigo-600" />
      </div>
      <h2 className="mt-4 text-lg font-semibold">Chat with your documents</h2>
      <p className="mt-1 max-w-md text-sm text-slate-500">
        {readyDocCount
          ? `Ask anything about the ${readyDocCount} file${readyDocCount > 1 ? "s" : ""} in this project. Answers cite their sources.`
          : "Upload files in the panel on the right. Once they are processed you can ask questions here."}
      </p>
      {readyDocCount > 0 && (
        <div className="mt-6 flex max-w-xl flex-wrap justify-center gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onPick(s)}
              className="rounded-full bg-white px-3 py-1.5 text-xs text-slate-600 ring-1 ring-slate-200 hover:bg-indigo-50 hover:text-indigo-700 hover:ring-indigo-200"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Turn "[3]" into a link the Markdown renderer can map to a citation chip. */
function linkCitations(text: string, sources: Source[] | null): string {
  if (!sources?.length) return text;
  const valid = new Set(sources.map((s) => s.index));
  return text.replace(/\[(\d{1,2})\](?!\()/g, (match, n) =>
    valid.has(Number(n)) ? `[${n}](#cite-${n})` : match,
  );
}

function AssistantMessage({
  message,
  onOpenSource,
}: {
  message: LocalMessage;
  onOpenSource: (s: Source) => void;
}) {
  const sources = message.sources ?? [];
  const cited = useMemo(() => {
    const set = new Set<number>();
    for (const m of message.content.matchAll(/\[(\d{1,2})\]/g)) set.add(Number(m[1]));
    return set;
  }, [message.content]);
  const content = useMemo(
    () => linkCitations(message.content, message.sources),
    [message.content, message.sources],
  );
  const shownSources = sources.filter((s) => cited.has(s.index));
  const waiting = message.streaming && !message.content;

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-indigo-50">
        <Sparkles className="size-4 text-indigo-600" />
      </div>
      <div className="min-w-0 flex-1">
        {waiting ? (
          <p className="flex items-center gap-2 py-1 text-sm text-slate-500">
            <Spinner className="size-4" />
            {message.sources ? `Reading ${message.sources.length} passages…` : "Searching your files…"}
          </p>
        ) : (
          <div
            className={cn(
              "prose prose-sm prose-slate max-w-none prose-pre:bg-slate-800 prose-table:text-xs",
              message.streaming && "stream-caret",
            )}
          >
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => {
                  if (href?.startsWith("#cite-")) {
                    const src = sources.find((s) => s.index === Number(href.slice(6)));
                    return (
                      <button
                        onClick={() => src && onOpenSource(src)}
                        title={src ? `${src.filename}${src.page ? `, p. ${src.page}` : ""}` : ""}
                        className="mx-0.5 inline-flex h-4 min-w-4 -translate-y-0.5 items-center justify-center rounded bg-indigo-100 px-1 align-middle text-[10px] font-semibold text-indigo-700 no-underline hover:bg-indigo-600 hover:text-white"
                      >
                        {children}
                      </button>
                    );
                  }
                  return (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  );
                },
              }}
            >
              {content}
            </Markdown>
          </div>
        )}
        {message.failed && !message.content && (
          <p className="text-sm text-red-600">The answer could not be generated.</p>
        )}

        {!message.streaming && shownSources.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {shownSources.map((s) => (
              <button
                key={s.index}
                onClick={() => onOpenSource(s)}
                className="inline-flex max-w-64 items-center gap-1.5 rounded-lg bg-white px-2 py-1 text-xs text-slate-600 ring-1 ring-slate-200 hover:ring-indigo-300"
              >
                <span className="font-semibold text-indigo-600">{s.index}</span>
                <FileText className="size-3 shrink-0 text-slate-400" />
                <span className="truncate">{s.filename}</span>
                {s.page && <span className="shrink-0 text-slate-400">p.{s.page}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SourceModal({ source, onClose }: { source: Source | null; onClose: () => void }) {
  if (!source) return null;
  const isPdf = source.filename.toLowerCase().endsWith(".pdf");
  const href = api.documentUrl(source.document_id) + (isPdf && source.page ? `#page=${source.page}` : "");
  return (
    <Modal
      open
      onClose={onClose}
      wide
      title={
        <span className="flex items-center gap-2">
          <BookOpen className="size-4 text-indigo-600" />
          Source [{source.index}] · {source.filename}
          {source.page ? <span className="font-normal text-slate-400">· page {source.page}</span> : null}
        </span>
      }
    >
      <p className="mb-2 text-xs text-slate-400">Passage retrieved for this answer</p>
      <div className="rounded-lg bg-slate-50 p-4 text-sm leading-relaxed whitespace-pre-wrap text-slate-700 ring-1 ring-slate-200">
        {source.content}
      </div>
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-indigo-600 hover:underline"
      >
        Open original file <ExternalLink className="size-3.5" />
      </a>
    </Modal>
  );
}
