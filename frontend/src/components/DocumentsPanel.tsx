import {
  CircleAlert,
  CircleCheck,
  Clock,
  Download,
  File as FileIcon,
  FileImage,
  FileSpreadsheet,
  FileText,
  LoaderCircle,
  Presentation,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api, uploadFiles, type DocumentItem, type UploadResult } from "../api";
import { cn, formatBytes, plural } from "../utils";
import { ErrorBanner, IconButton } from "./ui";

const ACCEPT_HINT = "PDF, Word, PowerPoint, Excel, CSV, text, Markdown, HTML, JSON, code, images";

function iconFor(doc: DocumentItem) {
  const name = doc.filename.toLowerCase();
  if (/\.(png|jpe?g|gif|webp)$/.test(name)) return FileImage;
  if (/\.(xlsx|xlsm|csv|tsv)$/.test(name)) return FileSpreadsheet;
  if (/\.(pptx|pptm)$/.test(name)) return Presentation;
  if (/\.(pdf|docx?|txt|md|html?)$/.test(name)) return FileText;
  return FileIcon;
}

function StatusBadge({ doc }: { doc: DocumentItem }) {
  switch (doc.status) {
    case "ready":
      return (
        <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
          <CircleCheck className="size-3.5" /> {plural(doc.num_chunks, "chunk")}
        </span>
      );
    case "processing":
      return (
        <span className="inline-flex items-center gap-1 text-xs text-indigo-600">
          <LoaderCircle className="size-3.5 animate-spin" /> Processing
        </span>
      );
    case "pending":
      return (
        <span className="inline-flex items-center gap-1 text-xs text-slate-500">
          <Clock className="size-3.5" /> Queued
        </span>
      );
    case "failed":
      return (
        <span className="inline-flex items-center gap-1 text-xs text-red-600" title={doc.error ?? ""}>
          <CircleAlert className="size-3.5" /> Failed
        </span>
      );
  }
}

export default function DocumentsPanel({
  projectId,
  selected,
  onSelectedChange,
  onDocumentsChange,
}: {
  projectId: string;
  selected: string[];
  onSelectedChange: (ids: string[]) => void;
  onDocumentsChange?: (docs: DocumentItem[]) => void;
}) {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listDocuments(projectId);
      setDocs(list);
      onDocumentsChange?.(list);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId, onDocumentsChange]);

  useEffect(() => {
    setLoaded(false);
    refresh();
  }, [refresh]);

  // Poll while anything is still being ingested.
  const busy = docs.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(refresh, 1500);
    return () => clearInterval(t);
  }, [busy, refresh]);

  // Drop selections for documents that no longer exist / aren't ready.
  useEffect(() => {
    const ready = new Set(docs.filter((d) => d.status === "ready").map((d) => d.id));
    const next = selected.filter((id) => ready.has(id));
    if (next.length !== selected.length) onSelectedChange(next);
  }, [docs, selected, onSelectedChange]);

  const upload = async (files: File[]) => {
    if (!files.length) return;
    setError(null);
    setNotice(null);
    setProgress(0);
    try {
      const result: UploadResult = await uploadFiles(projectId, files, setProgress);
      if (result.skipped.length) {
        setNotice(
          "Skipped: " + result.skipped.map((s) => `${s.filename} (${s.reason})`).join(", "),
        );
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProgress(null);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    upload(Array.from(e.dataTransfer.files));
  };

  const remove = async (doc: DocumentItem) => {
    if (!window.confirm(`Delete "${doc.filename}"? It will no longer be used in answers.`)) return;
    setDocs((d) => d.filter((x) => x.id !== doc.id));
    try {
      await api.deleteDocument(doc.id);
    } catch (e) {
      setError((e as Error).message);
    }
    refresh();
  };

  const reprocess = async (doc: DocumentItem) => {
    try {
      await api.reprocessDocument(doc.id);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggle = (id: string) =>
    onSelectedChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  const readyCount = docs.filter((d) => d.status === "ready").length;

  return (
    <div className="flex h-full flex-col">
      <div className="px-4 pt-4 pb-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Files</h2>
          <span className="text-xs text-slate-400">
            {readyCount}/{docs.length} ready
          </span>
        </div>

        <div
          onDragEnter={(e) => {
            e.preventDefault();
            dragDepth.current++;
            setDragging(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={() => {
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (dragDepth.current === 0) setDragging(false);
          }}
          onDrop={onDrop}
          onClick={() => progress === null && inputRef.current?.click()}
          className={cn(
            "mt-3 cursor-pointer rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors",
            dragging
              ? "border-indigo-500 bg-indigo-50"
              : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              upload(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
          {progress !== null ? (
            <div>
              <p className="text-sm font-medium text-slate-700">
                Uploading… {Math.round(progress * 100)}%
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-indigo-500 transition-[width]"
                  style={{ width: `${Math.round(progress * 100)}%` }}
                />
              </div>
            </div>
          ) : (
            <>
              <Upload className="mx-auto size-5 text-indigo-500" />
              <p className="mt-2 text-sm font-medium text-slate-700">
                Drop files or <span className="text-indigo-600">browse</span>
              </p>
              <p className="mt-1 text-[11px] leading-tight text-slate-400">{ACCEPT_HINT}</p>
            </>
          )}
        </div>

        <div className="mt-3 space-y-2">
          {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
          {notice && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
              {notice}
            </div>
          )}
        </div>
      </div>

      {readyCount > 0 && (
        <div className="flex items-center justify-between border-y border-slate-100 bg-slate-50/60 px-4 py-1.5 text-xs text-slate-500">
          <span>
            {selected.length
              ? `Chat limited to ${selected.length} file${selected.length > 1 ? "s" : ""}`
              : "Chat searches all files"}
          </span>
          {selected.length > 0 && (
            <button className="text-indigo-600 hover:underline" onClick={() => onSelectedChange([])}>
              Clear
            </button>
          )}
        </div>
      )}

      <ul className="scrollbar-thin flex-1 overflow-y-auto px-2 py-2">
        {loaded && docs.length === 0 && (
          <li className="px-2 py-6 text-center text-sm text-slate-400">No files yet.</li>
        )}
        {docs.map((doc) => {
          const Icon = iconFor(doc);
          const isReady = doc.status === "ready";
          return (
            <li
              key={doc.id}
              className="group flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-slate-50"
            >
              <input
                type="checkbox"
                disabled={!isReady}
                checked={selected.includes(doc.id)}
                onChange={() => toggle(doc.id)}
                title={isReady ? "Limit chat to selected files" : "Available once processed"}
                className="mt-1 size-3.5 rounded accent-indigo-600 disabled:opacity-30"
              />
              <Icon className="mt-0.5 size-4 shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-slate-800" title={doc.filename}>
                  {doc.filename}
                </p>
                <div className="flex items-center gap-2">
                  <StatusBadge doc={doc} />
                  <span className="text-xs text-slate-400">{formatBytes(doc.size_bytes)}</span>
                </div>
                {doc.status === "failed" && doc.error && (
                  <p className="mt-1 text-xs text-red-600/90">{doc.error}</p>
                )}
              </div>
              <div className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                {doc.status === "failed" && (
                  <IconButton label="Retry processing" onClick={() => reprocess(doc)} className="size-7">
                    <RefreshCw className="size-3.5" />
                  </IconButton>
                )}
                <a
                  href={api.documentUrl(doc.id)}
                  target="_blank"
                  rel="noreferrer"
                  title="Open file"
                  className="inline-flex size-7 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                >
                  <Download className="size-3.5" />
                </a>
                <IconButton
                  label="Delete file"
                  onClick={() => remove(doc)}
                  className="size-7 hover:text-red-600"
                >
                  <Trash2 className="size-3.5" />
                </IconButton>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
