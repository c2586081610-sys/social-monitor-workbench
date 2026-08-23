/** P6 待分类队列：未归类作品池 + 手动归类操作（选择分组 + 可选标签）。 */
import { useMemo, useState } from 'react';
import { FolderInput, Inbox } from 'lucide-react';
import WorkListItem from '../components/work/WorkListItem';
import Pagination from '../components/common/Pagination';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { listUnclassified } from '../services/unclassified';
import { listGroups } from '../services/groups';
import { classifyWork } from '../services/works';
import { useAsyncData, useMutation, usePolling } from '../hooks/useApi';
import { RUNNING_STATUSES } from '../utils/constants';

export default function UnclassifiedPage() {
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<number | null>(null);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [tagsText, setTagsText] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const queueQuery = useAsyncData(() => listUnclassified({ page, limit: 20 }), [page]);
  const groupsQuery = useAsyncData(() => listGroups(), []);
  const classifyMutation = useMutation(({ id, gid, tags }: { id: number; gid: number; tags: string[] }) =>
    classifyWork(id, { group_id: gid, tags }),
  );

  const items = queueQuery.data?.items ?? [];
  const hasRunning = useMemo(() => items.some((w) => RUNNING_STATUSES.has(w.status)), [items]);
  usePolling(queueQuery.refetch, hasRunning && !queueQuery.loading, 5000);

  const openClassify = (id: number) => {
    setOpenId(id);
    setGroupId(null);
    setTagsText('');
    setFormError(null);
  };

  const submit = async (id: number) => {
    setFormError(null);
    if (!groupId) return setFormError('请选择一个目标分组');
    const tags = tagsText
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean);
    try {
      await classifyMutation.run({ id, gid: groupId, tags });
      setOpenId(null);
      queueQuery.refetch();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : '归类失败');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Inbox className="h-5 w-5 text-primary" />
        <div>
          <h1 className="text-lg font-semibold text-ink">待分类队列</h1>
          <p className="text-xs text-ink-muted">未归类作品池：手动选择分组归类后，将移入对应分组目录（media + Obsidian 双目录）。</p>
        </div>
      </div>

      {queueQuery.loading ? (
        <LoadingState label="加载待分类作品…" />
      ) : queueQuery.error ? (
        <ErrorState message={queueQuery.error.message} onRetry={queueQuery.refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Inbox className="h-5 w-5" />}
          title="暂无待分类作品"
          hint="抖音点赞/收藏自动检测（P2）完成后，作品会落入这里等待归类；当前可先通过作品详情为作品打标签。"
        />
      ) : (
        <>
          <div className="space-y-3">
            {items.map((w) => (
              <div key={w.id} className="space-y-2">
                <WorkListItem work={w} onChanged={queueQuery.refetch} />
                {openId === w.id ? (
                  <div className="rounded-lg border border-primary/30 bg-primary-light p-3">
                    <p className="mb-2 text-xs font-medium text-primary">归类到分组</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <select
                        value={groupId ?? ''}
                        onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : null)}
                        className="rounded-md border border-line bg-surface px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
                      >
                        <option value="">选择分组…</option>
                        {(groupsQuery.data?.items ?? []).map((g) => (
                          <option key={g.id} value={g.id}>{g.name}</option>
                        ))}
                      </select>
                      <input
                        value={tagsText}
                        onChange={(e) => setTagsText(e.target.value)}
                        placeholder="确认标签（逗号分隔，可选）"
                        className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => submit(w.id)}
                        disabled={classifyMutation.loading}
                        className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover disabled:opacity-60"
                      >
                        <FolderInput className="h-4 w-4" />
                        确认归类
                      </button>
                      <button
                        type="button"
                        onClick={() => setOpenId(null)}
                        className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar"
                      >
                        取消
                      </button>
                    </div>
                    {formError ? <p className="mt-2 text-xs text-danger">{formError}</p> : null}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => openClassify(w.id)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:bg-sidebar hover:text-primary"
                  >
                    <FolderInput className="h-3.5 w-3.5" />
                    归类
                  </button>
                )}
              </div>
            ))}
          </div>
          <Pagination
            page={page}
            limit={20}
            total={queueQuery.data?.total ?? 0}
            onChange={setPage}
          />
        </>
      )}
    </div>
  );
}
