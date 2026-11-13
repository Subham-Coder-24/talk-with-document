import { ArrowLeft, Files, MessageSquare, PanelLeft, Pencil, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, type Conversation, type DocumentItem, type Project } from "../api";
import ChatPanel from "../components/ChatPanel";
import DocumentsPanel from "../components/DocumentsPanel";
import { ErrorBanner, IconButton, Spinner } from "../components/ui";
import { cn, timeAgo } from "../utils";

export default function ProjectPage() {
  const { projectId = "", conversationId } = useParams();
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [readyDocCount, setReadyDocCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // Mobile/tablet drawers
  const [showChats, setShowChats] = useState(false);
  const [showFiles, setShowFiles] = useState(false);

  useEffect(() => {
    setProject(null);
    setNotFound(false);
    setSelectedDocs([]);
    api
      .getProject(projectId)
      .then(setProject)
      .catch((e) => (e.status === 404 ? setNotFound(true) : setError(e.message)));
  }, [projectId]);

  const loadConversations = useCallback(() => {
    api
      .listConversations(projectId)
      .then(setConversations)
      .catch((e) => setError(e.message));
  }, [projectId]);

  useEffect(loadConversations, [loadConversations]);

  const onDocumentsChange = useCallback((docs: DocumentItem[]) => {
    setReadyDocCount(docs.filter((d) => d.status === "ready").length);
  }, []);

  const openConversation = (id?: string) => {
    setShowChats(false);
    navigate(id ? `/projects/${projectId}/c/${id}` : `/projects/${projectId}`);
  };

  const rename = async (c: Conversation) => {
    const title = window.prompt("Rename chat", c.title)?.trim();
    if (!title || title === c.title) return;
    try {
      await api.renameConversation(c.id, title);
      loadConversations();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (c: Conversation) => {
    if (!window.confirm(`Delete chat "${c.title}"?`)) return;
    try {
      await api.deleteConversation(c.id);
      if (c.id === conversationId) openConversation();
      loadConversations();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (notFound) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-slate-600">This project doesn't exist or was deleted.</p>
        <Link to="/" className="text-sm font-medium text-indigo-600 hover:underline">
          Back to projects
        </Link>
      </div>
    );
  }

  const chatList = (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <button
          onClick={() => openConversation()}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500"
        >
          <Plus className="size-4" /> New chat
        </button>
      </div>
      <p className="px-4 pt-1 pb-2 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
        Chats
      </p>
      <ul className="scrollbar-thin flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 && (
          <li className="px-2 py-4 text-center text-xs text-slate-400">No chats yet</li>
        )}
        {conversations.map((c) => (
          <li key={c.id} className="group relative">
            <button
              onClick={() => openConversation(c.id)}
              className={cn(
                "flex w-full flex-col rounded-lg px-3 py-2 pr-16 text-left transition-colors",
                c.id === conversationId ? "bg-indigo-50 text-indigo-900" : "hover:bg-slate-100",
              )}
            >
              <span className="truncate text-sm">{c.title}</span>
              <span className="text-[11px] text-slate-400">{timeAgo(c.updated_at)}</span>
            </button>
            <div className="absolute top-1/2 right-1 flex -translate-y-1/2 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
              <IconButton label="Rename chat" className="size-7" onClick={() => rename(c)}>
                <Pencil className="size-3.5" />
              </IconButton>
              <IconButton
                label="Delete chat"
                className="size-7 hover:text-red-600"
                onClick={() => remove(c)}
              >
                <Trash2 className="size-3.5" />
              </IconButton>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );

  const filesPanel = (
    <DocumentsPanel
      projectId={projectId}
      selected={selectedDocs}
      onSelectedChange={setSelectedDocs}
      onDocumentsChange={onDocumentsChange}
    />
  );

  return (
    <div className="flex h-full flex-col">
      {/* Top bar */}
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3">
        <IconButton label="Chats" className="md:hidden" onClick={() => setShowChats(true)}>
          <PanelLeft className="size-4" />
        </IconButton>
        <Link
          to="/"
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        >
          <ArrowLeft className="size-4" />
          <span className="hidden sm:inline">Projects</span>
        </Link>
        <span className="text-slate-300">/</span>
        {project ? (
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">{project.name}</h1>
            {project.description && (
              <p className="truncate text-xs text-slate-400">{project.description}</p>
            )}
          </div>
        ) : (
          <div className="flex-1">
            <Spinner className="size-4" />
          </div>
        )}
        <button
          onClick={() => setShowFiles(true)}
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50 lg:hidden"
        >
          <Files className="size-4" /> Files
        </button>
      </header>

      {error && (
        <div className="px-4 pt-3">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* Conversations */}
        <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white md:block">
          {chatList}
        </aside>

        {/* Chat */}
        <main className="min-w-0 flex-1 bg-slate-50">
          <ChatPanel
            projectId={projectId}
            conversationId={conversationId}
            documentIds={selectedDocs}
            readyDocCount={readyDocCount}
            onConversationCreated={(id) => {
              navigate(`/projects/${projectId}/c/${id}`);
              loadConversations();
            }}
            onConversationUpdated={loadConversations}
          />
        </main>

        {/* Files (always mounted so polling/selection persists) */}
        <aside
          className={cn(
            "w-80 shrink-0 border-l border-slate-200 bg-white",
            "max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:z-40 max-lg:shadow-2xl max-lg:transition-transform",
            showFiles ? "max-lg:translate-x-0" : "max-lg:translate-x-full",
          )}
        >
          <div className="flex h-12 items-center justify-end border-b border-slate-100 px-2 lg:hidden">
            <IconButton label="Close files" onClick={() => setShowFiles(false)}>
              <X className="size-4" />
            </IconButton>
          </div>
          <div className="h-full max-lg:h-[calc(100%-3rem)]">{filesPanel}</div>
        </aside>
      </div>

      {/* Mobile chats drawer */}
      {showChats && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-slate-900/30" onClick={() => setShowChats(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-2xl">
            <div className="flex h-12 items-center justify-between border-b border-slate-100 px-3">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <MessageSquare className="size-4" /> Chats
              </span>
              <IconButton label="Close" onClick={() => setShowChats(false)}>
                <X className="size-4" />
              </IconButton>
            </div>
            <div className="h-[calc(100%-3rem)]">{chatList}</div>
          </aside>
        </div>
      )}
      {showFiles && (
        <div className="fixed inset-0 z-30 bg-slate-900/30 lg:hidden" onClick={() => setShowFiles(false)} />
      )}
    </div>
  );
}
