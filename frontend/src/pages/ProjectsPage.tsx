import { FileText, FolderPlus, MessageSquare, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api, type Project } from "../api";
import { Button, ErrorBanner, IconButton, Logo, Modal, Spinner } from "../components/ui";
import { plural, timeAgo } from "../utils";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("");
  const [toDelete, setToDelete] = useState<Project | null>(null);

  const load = () =>
    api
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!projects || !q) return projects;
    return projects.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.description ?? "").toLowerCase().includes(q),
    );
  }, [projects, filter]);

  return (
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Logo />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
            <p className="mt-1 text-sm text-slate-500">
              Group related files into a project, then chat with them.
            </p>
          </div>
          <div className="flex gap-2">
            <label className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-slate-400" />
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search projects"
                className="w-48 rounded-lg border-0 bg-white py-2 pr-3 pl-8 text-sm ring-1 ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              />
            </label>
            <Button onClick={() => setCreating(true)}>
              <FolderPlus className="size-4" /> New project
            </Button>
          </div>
        </div>

        {error && (
          <div className="mt-6">
            <ErrorBanner message={error} onDismiss={() => setError(null)} />
          </div>
        )}

        {projects === null && !error ? (
          <div className="mt-16 flex justify-center">
            <Spinner />
          </div>
        ) : projects && projects.length === 0 ? (
          <EmptyState onCreate={() => setCreating(true)} />
        ) : (
          <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {visible?.map((p) => (
              <li key={p.id} className="group relative">
                <Link
                  to={`/projects/${p.id}`}
                  className="flex h-full flex-col rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md hover:ring-indigo-300"
                >
                  <div className="flex items-start gap-3 pr-8">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-lg font-semibold text-indigo-600">
                      {p.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold text-slate-900">{p.name}</h3>
                      <p className="text-xs text-slate-400">Updated {timeAgo(p.updated_at)}</p>
                    </div>
                  </div>
                  <p className="mt-3 line-clamp-2 min-h-10 text-sm text-slate-500">
                    {p.description || "No description"}
                  </p>
                  <div className="mt-4 flex gap-4 text-xs text-slate-500">
                    <span className="flex items-center gap-1">
                      <FileText className="size-3.5" /> {plural(p.document_count, "file")}
                    </span>
                    <span className="flex items-center gap-1">
                      <MessageSquare className="size-3.5" /> {plural(p.conversation_count, "chat")}
                    </span>
                  </div>
                </Link>
                <IconButton
                  label="Delete project"
                  onClick={() => setToDelete(p)}
                  className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-red-600"
                >
                  <Trash2 className="size-4" />
                </IconButton>
              </li>
            ))}
          </ul>
        )}
      </main>

      <CreateProjectModal open={creating} onClose={() => setCreating(false)} />
      <DeleteProjectModal
        project={toDelete}
        onClose={() => setToDelete(null)}
        onDeleted={() => {
          setToDelete(null);
          load();
        }}
      />
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="mt-10 rounded-2xl border-2 border-dashed border-slate-200 bg-white px-6 py-16 text-center">
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-indigo-50">
        <FolderPlus className="size-6 text-indigo-600" />
      </div>
      <h3 className="mt-4 font-semibold">No projects yet</h3>
      <p className="mx-auto mt-1 max-w-sm text-sm text-slate-500">
        Create a project, upload PDFs, Word, Excel, PowerPoint, text or image files, and ask
        questions about them.
      </p>
      <Button className="mt-6" onClick={onCreate}>
        <FolderPlus className="size-4" /> Create your first project
      </Button>
    </div>
  );
}

function CreateProjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const p = await api.createProject(name.trim(), description.trim());
      navigate(`/projects/${p.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="New project">
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Name</span>
          <input
            autoFocus
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Q3 Vendor Contracts"
            className="mt-1 w-full rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">
            Description <span className="font-normal text-slate-400">(optional)</span>
          </span>
          <textarea
            rows={3}
            maxLength={2000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="mt-1 w-full resize-none rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          />
        </label>
        {error && <ErrorBanner message={error} />}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={saving} disabled={!name.trim()}>
            Create project
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteProjectModal({
  project,
  onClose,
  onDeleted,
}: {
  project: Project | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (!project) return;
    setBusy(true);
    try {
      await api.deleteProject(project.id);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={!!project} onClose={onClose} title="Delete project?">
      <p className="text-sm text-slate-600">
        <strong>{project?.name}</strong> and all its files ({project?.document_count}) and chats (
        {project?.conversation_count}) will be permanently deleted.
      </p>
      {error && (
        <div className="mt-3">
          <ErrorBanner message={error} />
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="danger" loading={busy} onClick={confirm}>
          Delete
        </Button>
      </div>
    </Modal>
  );
}
