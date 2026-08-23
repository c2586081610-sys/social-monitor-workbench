/** P2 分组管理：分组侧边栏 + 分组 CRUD（增/改/删）+ 按分组过滤博主。 */
import { useMemo, useState } from 'react';
import { Check, Folder, FolderPlus, Pencil, Trash2, X } from 'lucide-react';
import CreatorCard from '../components/creator/CreatorCard';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { createGroup, deleteGroup, listGroups, renameGroup } from '../services/groups';
import { listCreators } from '../services/creators';
import { useAsyncData, useMutation } from '../hooks/useApi';
import type { Group } from '../types/api.d';

type Selection = 'all' | 'none' | number;

export default function GroupsPage() {
  const [selection, setSelection] = useState<Selection>('all');
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<Group | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const groupsQuery = useAsyncData(() => listGroups(), []);
  const creatorsQuery = useAsyncData(() => listCreators({ page: 1, limit: 100 }), []);

  const createMutation = useMutation((name: string) => createGroup(name));
  const renameMutation = useMutation(({ id, name }: { id: number; name: string }) => renameGroup(id, name));
  const deleteMutation = useMutation((id: number) => deleteGroup(id));

  const groups = groupsQuery.data?.items ?? [];
  const allCreators = creatorsQuery.data?.items ?? [];

  const filteredCreators = useMemo(() => {
    if (selection === 'all') return allCreators;
    if (selection === 'none') return allCreators.filter((c) => c.group_id === null);
    return allCreators.filter((c) => c.group_id === selection);
  }, [allCreators, selection]);

  const groupNameOf = (id: number | null) => groups.find((g) => g.id === id)?.name;

  const handleCreate = async () => {
    setFormError(null);
    const name = newName.trim();
    if (!name) return;
    try {
      await createMutation.run(name);
      setNewName('');
      groupsQuery.refetch();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : '创建失败');
    }
  };

  const handleRename = async (id: number) => {
    const name = editName.trim();
    if (!name) return;
    try {
      await renameMutation.run({ id, name });
      setEditingId(null);
      groupsQuery.refetch();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : '重命名失败');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMutation.run(deleteTarget.id);
      setDeleteTarget(null);
      groupsQuery.refetch();
      creatorsQuery.refetch();
      if (selection === deleteTarget.id) setSelection('all');
    } catch (e) {
      setFormError(e instanceof Error ? e.message : '删除失败');
      setDeleteTarget(null);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-ink">分组管理</h1>
        <p className="text-xs text-ink-muted">一个博主只归一组；删除分组后组内博主移入「未分组」，作品保留。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        {/* 分组侧边栏 */}
        <aside className="rounded-lg border border-line bg-surface p-3 shadow-card">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-ink-muted">分组</h2>
          <div className="flex gap-1.5 pb-2">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="新分组名"
              className="min-w-0 flex-1 rounded-md border border-line px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
            />
            <button
              type="button"
              onClick={handleCreate}
              disabled={createMutation.loading}
              className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover disabled:opacity-60"
              title="新建分组"
            >
              <FolderPlus className="h-4 w-4" />
            </button>
          </div>

          <nav className="space-y-1">
            <button
              type="button"
              onClick={() => setSelection('all')}
              className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                selection === 'all' ? 'bg-primary-light text-primary' : 'text-ink-secondary hover:bg-sidebar'
              }`}
            >
              <Folder className="h-4 w-4" />全部博主
            </button>
            <button
              type="button"
              onClick={() => setSelection('none')}
              className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                selection === 'none' ? 'bg-primary-light text-primary' : 'text-ink-secondary hover:bg-sidebar'
              }`}
            >
              <Folder className="h-4 w-4" />未分组
            </button>

            {groups.map((g) => (
              <div
                key={g.id}
                className={`group flex items-center gap-1 rounded-md px-1 transition-colors ${
                  selection === g.id ? 'bg-primary-light' : 'hover:bg-sidebar'
                }`}
              >
                <button
                  type="button"
                  onClick={() => setSelection(g.id)}
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1.5 text-sm text-ink-secondary"
                >
                  <Folder className="h-4 w-4 shrink-0 text-ink-muted" />
                  <span className="truncate-1">{g.name}</span>
                  <span className="ml-auto shrink-0 text-xs text-ink-muted">{g.creator_count}</span>
                </button>
                {editingId === g.id ? (
                  <span className="flex shrink-0 items-center gap-0.5">
                    <input
                      autoFocus
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleRename(g.id)}
                      className="w-20 rounded border border-primary px-1 text-xs focus:outline-none"
                    />
                    <button type="button" onClick={() => handleRename(g.id)} className="p-1 text-success" aria-label="保存">
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" onClick={() => setEditingId(null)} className="p-1 text-ink-muted" aria-label="取消">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ) : (
                  <span className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(g.id);
                        setEditName(g.name);
                      }}
                      className="p-1 text-ink-muted hover:text-primary"
                      aria-label="重命名"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(g)}
                      className="p-1 text-ink-muted hover:text-danger"
                      aria-label="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                )}
              </div>
            ))}
          </nav>
        </aside>

        {/* 右侧博主列表 */}
        <section>
          {formError ? <p className="mb-3 rounded-md bg-danger-light px-3 py-2 text-sm text-danger">{formError}</p> : null}
          {creatorsQuery.loading ? (
            <LoadingState label="加载博主…" />
          ) : creatorsQuery.error ? (
            <ErrorState message={creatorsQuery.error.message} onRetry={creatorsQuery.refetch} />
          ) : filteredCreators.length === 0 ? (
            <EmptyState
              title={selection === 'all' ? '还没有博主' : selection === 'none' ? '没有未分组博主' : '该分组暂无博主'}
              hint="可回到首页添加博主，或在该分组下等待新博主加入。"
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {filteredCreators.map((c) => (
                <CreatorCard
                  key={c.id}
                  creator={c}
                  groupName={groupNameOf(c.group_id)}
                  onChanged={creatorsQuery.refetch}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除分组"
        message={
          deleteTarget
            ? `确定删除分组「${deleteTarget.name}」？组内 ${deleteTarget.creator_count} 位博主将移入「未分组」，作品全部保留。`
            : ''
        }
        loading={deleteMutation.loading}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
