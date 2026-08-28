/** P5 标签检索：标签云/标签列表 → 点击标签 → 含该标签的作品列表（双层标签 big/small）。 */
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Tags } from 'lucide-react';
import WorkListItem from '../components/work/WorkListItem';
import Pagination from '../components/common/Pagination';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { listTags, listWorksByTag } from '../services/tags';
import { useAsyncData, usePolling } from '../hooks/useApi';
import { RUNNING_STATUSES } from '../utils/constants';

export default function TagsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = searchParams.get('tag') ?? '';
  const page = Number(searchParams.get('page') ?? '1');

  const tagsQuery = useAsyncData(() => listTags(), []);
  const worksQuery = useAsyncData(
    () => (selected ? listWorksByTag(selected, { page, limit: 20 }) : Promise.resolve(null)),
    [selected, page],
  );

  const works = worksQuery.data?.items ?? [];
  const hasRunning = useMemo(() => works.some((w) => RUNNING_STATUSES.has(w.status)), [works]);
  usePolling(worksQuery.refetch, hasRunning && !!selected && !worksQuery.loading, 5000);

  const tags = tagsQuery.data?.items ?? [];
  const bigTags = tags.filter((t) => t.kind === 'big');
  const smallTags = tags.filter((t) => t.kind === 'small');

  const selectTag = (name: string) => {
    setSearchParams(name ? { tag: name } : {});
  };

  const changePage = (p: number) => {
    setSearchParams({ tag: selected, page: String(p) });
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-ink">标签检索</h1>
        <p className="text-xs text-ink-muted">大标签（#财经）与小标签（#美联储）由 AI 笔记生成，点击即可检索全库作品。</p>
      </div>

      <section className="rounded-lg border border-line bg-surface p-4 shadow-card">
        {tagsQuery.loading ? (
          <LoadingState label="加载标签…" />
        ) : tags.length === 0 ? (
          <p className="text-xs text-ink-muted">暂无标签，AI 笔记生成后将自动聚合。</p>
        ) : (
          <>
            {bigTags.length > 0 ? (
              <div>
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-ink-muted">大标签</h2>
                <div className="flex flex-wrap gap-2">
                  {bigTags.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => selectTag(t.name)}
                      className={`rounded-full px-3 py-1.5 text-sm font-semibold transition-colors ${
                        selected === t.name
                          ? 'bg-primary text-white'
                          : 'bg-primary-light text-primary hover:bg-primary hover:text-white'
                      }`}
                    >
                      #{t.name}（{t.work_count}）
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {smallTags.length > 0 ? (
              <div className={bigTags.length > 0 ? 'mt-5' : ''}>
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-ink-muted">小标签</h2>
                <div className="flex flex-wrap gap-2">
                  {smallTags.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => selectTag(t.name)}
                      className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                        selected === t.name
                          ? 'bg-primary text-white'
                          : 'border border-line bg-surface text-ink-secondary hover:bg-sidebar'
                      }`}
                    >
                      #{t.name}（{t.work_count}）
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        )}
      </section>

      {selected ? (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <Tags className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-ink">包含「#{selected}」的作品</h2>
            <span className="text-xs text-ink-muted">共 {worksQuery.data?.total ?? 0} 条</span>
          </div>
          {worksQuery.loading ? (
            <LoadingState label="加载作品…" />
          ) : worksQuery.error ? (
            <ErrorState message={worksQuery.error.message} onRetry={worksQuery.refetch} />
          ) : works.length === 0 ? (
            <EmptyState title="该标签下暂无作品" hint="可切换其他标签查看。" />
          ) : (
            <>
              <div className="space-y-3">
                {works.map((w) => (
                  <WorkListItem key={w.id} work={w} onChanged={worksQuery.refetch} />
                ))}
              </div>
              <Pagination
                page={page}
                limit={20}
                total={worksQuery.data?.total ?? 0}
                onChange={changePage}
              />
            </>
          )}
        </section>
      ) : (
        <EmptyState
          icon={<Tags className="h-5 w-5" />}
          title="点击上方标签开始检索"
          hint="选择大标签或小标签后，将列出所有包含该标签的作品。"
        />
      )}
    </div>
  );
}
