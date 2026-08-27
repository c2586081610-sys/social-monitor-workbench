/** P7 词库管理：词条 CRUD（增/删/改/查 + 启停），驱动语义对齐抽帧。
 *  v3：标签云 chips + 兴趣区间分组（finance/ai/fitness/business/general）+ 搜索过滤。
 */
import { useMemo, useState } from 'react';
import { Plus, Search, X } from 'lucide-react';
import Modal from '../components/common/Modal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import {
  createLexiconEntry,
  deleteLexiconEntry,
  listLexicon,
  updateLexiconEntry,
} from '../services/lexicon';
import { useAsyncData, useMutation } from '../hooks/useApi';
import { formatDateTime } from '../utils/format';
import type { LexiconItem } from '../types/api.d';

/** 兴趣区间（与后端 category 取值对齐） */
const CATEGORIES: { key: string; label: string }[] = [
  { key: 'finance', label: '金融理财' },
  { key: 'ai', label: '科技AI' },
  { key: 'fitness', label: '健身饮食' },
  { key: 'business', label: '赚钱小买卖' },
  { key: 'general', label: '通用视觉' },
];

/** 区间 → 色标（纯色分类色，非渐变） */
const CATEGORY_STYLE: Record<string, { bg: string; text: string }> = {
  finance: { bg: 'bg-amber-100', text: 'text-amber-900' },
  ai: { bg: 'bg-blue-100', text: 'text-blue-900' },
  fitness: { bg: 'bg-green-100', text: 'text-green-900' },
  business: { bg: 'bg-teal-100', text: 'text-teal-900' },
  general: { bg: 'bg-gray-100', text: 'text-gray-800' },
};

const UNCATEGORIZED_STYLE = { bg: 'bg-gray-50', text: 'text-gray-600' };

function categoryLabel(key: string | null | undefined): string {
  if (!key) return '未分类';
  return CATEGORIES.find((c) => c.key === key)?.label ?? key;
}

function categoryStyle(key: string | null | undefined) {
  return (key && CATEGORY_STYLE[key]) || UNCATEGORIZED_STYLE;
}

/** 权重 → 字号（px）：weight 0.5→12px，1.0→14px，2.0→18px */
function weightFontSize(weight: number): number {
  return Math.min(18, Math.max(12, Math.round(12 + (weight - 0.5) * 4)));
}

interface FormState {
  term: string;
  action: 'increase' | 'decrease';
  weight: number;
  enabled: boolean;
  platform_scope: string;
  category: string;
}

const EMPTY_FORM: FormState = { term: '', action: 'increase', weight: 1, enabled: true, platform_scope: '', category: '' };

const inputClass =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none';

export default function LexiconPage() {
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<LexiconItem | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LexiconItem | null>(null);
  const [queryText, setQueryText] = useState('');

  const query = useAsyncData(() => listLexicon(), []);
  const createMutation = useMutation((f: FormState) =>
    createLexiconEntry({
      term: f.term,
      action: f.action,
      weight: f.weight,
      enabled: f.enabled,
      platform_scope: f.platform_scope || null,
      category: f.category || null,
    }),
  );
  const updateMutation = useMutation(({ id, f }: { id: number; f: FormState }) =>
    updateLexiconEntry(id, {
      term: f.term,
      action: f.action,
      weight: f.weight,
      enabled: f.enabled,
      platform_scope: f.platform_scope || null,
      category: f.category || null,
    }),
  );
  const deleteMutation = useMutation((id: number) => deleteLexiconEntry(id));

  const items = query.data?.items ?? [];

  const filtered = useMemo(() => {
    const q = queryText.trim().toLowerCase();
    if (!q) return items;
    return items.filter((i) => i.term.toLowerCase().includes(q));
  }, [items, queryText]);

  const enabledCount = items.filter((i) => i.enabled).length;

  /** 按区间分组（固定顺序 + 未分类兜底），仅含非空组 */
  const groups = useMemo(() => {
    const result: { key: string; label: string; items: LexiconItem[] }[] = [];
    for (const cat of CATEGORIES) {
      const groupItems = filtered.filter((i) => (i.category ?? '') === cat.key);
      if (groupItems.length) result.push({ key: cat.key, label: cat.label, items: groupItems });
    }
    const rest = filtered.filter((i) => {
      const c = i.category ?? '';
      return !CATEGORIES.some((cat) => cat.key === c);
    });
    if (rest.length) result.push({ key: '__uncategorized__', label: '未分类', items: rest });
    return result;
  }, [filtered]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (item: LexiconItem) => {
    setEditing(item);
    setForm({
      term: item.term,
      action: item.action,
      weight: item.weight,
      enabled: item.enabled,
      platform_scope: item.platform_scope ?? '',
      category: item.category ?? '',
    });
    setFormError(null);
    setFormOpen(true);
  };

  const submit = async () => {
    setFormError(null);
    const term = form.term.trim();
    if (!term) return setFormError('请填写触发词');
    if (form.weight <= 0) return setFormError('权重需大于 0');
    try {
      if (editing) await updateMutation.run({ id: editing.id, f: form });
      else await createMutation.run(form);
      setFormOpen(false);
      query.refetch();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : '保存失败');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMutation.run(deleteTarget.id);
      setDeleteTarget(null);
      query.refetch();
    } catch (e) {
      setDeleteTarget(null);
    }
  };

  const saving = createMutation.loading || updateMutation.loading;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">词库管理</h1>
          <p className="text-xs text-ink-muted">
            转写稿命中启用中的词条后，按动作与权重量化增删对应时间窗口的关键帧。词条按兴趣区间分组，四平台统一生效。
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover"
        >
          <Plus className="h-4 w-4" />
          新增词条
        </button>
      </div>

      {query.loading ? (
        <LoadingState label="加载词库…" />
      ) : query.error ? (
        <ErrorState message={query.error.message} onRetry={query.refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          title="词库为空"
          hint="新增词条（如 A股 / 走势 / 表格），转写稿命中后将按语义时间窗口增加关键帧。"
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[220px] flex-1 sm:max-w-xs">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
              <input
                value={queryText}
                onChange={(e) => setQueryText(e.target.value)}
                placeholder="搜索词条…"
                className={`${inputClass} pl-9 pr-8`}
              />
              {queryText ? (
                <button
                  type="button"
                  onClick={() => setQueryText('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-muted transition-colors hover:text-ink"
                  aria-label="清空搜索"
                >
                  <X className="h-4 w-4" />
                </button>
              ) : null}
            </div>
            <p className="text-xs text-ink-muted">
              共 {items.length} 词 · 启用 {enabledCount} 个
              {queryText ? ` · 命中 ${filtered.length} 个` : ''}
            </p>
          </div>

          {filtered.length === 0 ? (
            <div className="rounded-lg border border-line bg-surface p-8 text-center text-sm text-ink-muted">
              没有匹配「{queryText}」的词条
            </div>
          ) : (
            <div className="space-y-5">
              {groups.map((group) => {
                const gStyle = group.key === '__uncategorized__' ? UNCATEGORIZED_STYLE : CATEGORY_STYLE[group.key] ?? UNCATEGORIZED_STYLE;
                return (
                  <section key={group.key}>
                    <div className="mb-2 flex items-center gap-2">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${gStyle.bg} ${gStyle.text}`}>
                        {group.label}
                      </span>
                      <span className="text-xs text-ink-muted">{group.items.length} 词</span>
                    </div>
                    <div className="flex flex-wrap gap-2 rounded-lg border border-line bg-surface p-4 shadow-card">
                      {group.items.map((item) => {
                        const cs = categoryStyle(item.category);
                        const disabled = !item.enabled;
                        return (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => openEdit(item)}
                            title={`${item.term}（${categoryLabel(item.category)}）· 权重 ${item.weight} · 点击编辑`}
                            className={`group relative inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 transition-colors hover:border-primary hover:bg-primary/5 ${cs.bg} ${
                              cs.text
                            } ${disabled ? 'opacity-40 hover:opacity-70' : ''}`}
                          >
                            <span style={{ fontSize: weightFontSize(item.weight), lineHeight: 1.2 }}>{item.term}</span>
                            <span className="font-mono text-xs opacity-70">×{item.weight}</span>
                            <span
                              title={item.action === 'increase' ? '增加关键帧' : '减少关键帧'}
                              className={`rounded px-1 text-[11px] font-medium ${
                                item.action === 'increase' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                              }`}
                            >
                              {item.action === 'increase' ? '增' : '减'}
                            </span>
                            <span
                              role="button"
                              tabIndex={-1}
                              onClick={(e) => {
                                e.stopPropagation();
                                setDeleteTarget(item);
                              }}
                              className="ml-0.5 rounded-full p-0.5 text-ink-muted opacity-0 transition-opacity hover:bg-white/60 hover:text-danger group-hover:opacity-100"
                              title="删除词条"
                            >
                              <X className="h-3.5 w-3.5" />
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* 新增/编辑弹窗 */}
      <Modal
        open={formOpen}
        title={editing ? '编辑词条' : '新增词条'}
        onClose={() => setFormOpen(false)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setFormOpen(false)}
              className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar"
            >
              取消
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={saving}
              className="rounded-md bg-primary px-3 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover disabled:opacity-60"
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-ink">触发词</label>
            <input value={form.term} onChange={(e) => setForm({ ...form, term: e.target.value })} placeholder="如：A股" className={inputClass} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-ink">兴趣区间</label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className={inputClass}>
              <option value="">未分类</option>
              {CATEGORIES.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-ink">动作</label>
              <select value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value as FormState['action'] })} className={inputClass}>
                <option value="increase">增加关键帧</option>
                <option value="decrease">减少关键帧</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-ink">权重</label>
              <input type="number" step="0.5" min="0.1" value={form.weight} onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })} className={inputClass} />
            </div>
          </div>
          {editing ? (
            <p className="text-xs text-ink-muted">创建时间：{formatDateTime(editing.created_at)}</p>
          ) : null}
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} className="h-4 w-4 accent-primary" />
            启用该词条
          </label>
          {formError ? <p className="text-sm text-danger">{formError}</p> : null}
        </div>
      </Modal>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除词条"
        message={deleteTarget ? `确定删除词条「${deleteTarget.term}」？删除后不再触发抽帧。` : ''}
        loading={deleteMutation.loading}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
