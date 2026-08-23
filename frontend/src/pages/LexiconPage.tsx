/** P7 词库管理：词条 CRUD（增/删/改/查 + 启停），驱动语义对齐抽帧。 */
import { useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import Modal from '../components/common/Modal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StateViews';
import { ToneBadge } from '../components/common/StatusBadge';
import {
  createLexiconEntry,
  deleteLexiconEntry,
  listLexicon,
  updateLexiconEntry,
} from '../services/lexicon';
import { useAsyncData, useMutation } from '../hooks/useApi';
import { formatDateTime } from '../utils/format';
import type { LexiconItem } from '../types/api.d';

interface FormState {
  term: string;
  action: 'increase' | 'decrease';
  weight: number;
  enabled: boolean;
  platform_scope: string;
}

const EMPTY_FORM: FormState = { term: '', action: 'increase', weight: 1, enabled: true, platform_scope: '' };

const inputClass =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none';

export default function LexiconPage() {
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<LexiconItem | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LexiconItem | null>(null);

  const query = useAsyncData(() => listLexicon(), []);
  const createMutation = useMutation((f: FormState) =>
    createLexiconEntry({
      term: f.term,
      action: f.action,
      weight: f.weight,
      enabled: f.enabled,
      platform_scope: f.platform_scope || null,
    }),
  );
  const updateMutation = useMutation(({ id, f }: { id: number; f: FormState }) =>
    updateLexiconEntry(id, {
      term: f.term,
      action: f.action,
      weight: f.weight,
      enabled: f.enabled,
      platform_scope: f.platform_scope || null,
    }),
  );
  const deleteMutation = useMutation((id: number) => deleteLexiconEntry(id));
  const toggleMutation = useMutation(({ id, enabled }: { id: number; enabled: boolean }) =>
    updateLexiconEntry(id, { enabled }),
  );

  const items = query.data?.items ?? [];

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
          <p className="text-xs text-ink-muted">转写稿命中启用中的词条后，按动作与权重量化增删对应时间窗口的关键帧。</p>
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
        <div className="overflow-x-auto rounded-lg border border-line bg-surface shadow-card">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-widest text-ink-muted">
                <th className="px-4 py-2.5 font-semibold">触发词</th>
                <th className="px-4 py-2.5 font-semibold">动作</th>
                <th className="px-4 py-2.5 font-semibold">权重</th>
                <th className="px-4 py-2.5 font-semibold">启用</th>
                <th className="px-4 py-2.5 font-semibold">生效平台</th>
                <th className="px-4 py-2.5 font-semibold">创建时间</th>
                <th className="px-4 py-2.5 text-right font-semibold">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {items.map((item) => (
                <tr key={item.id} className="transition-colors hover:bg-sidebar/50">
                  <td className="px-4 py-2.5 font-medium text-ink">{item.term}</td>
                  <td className="px-4 py-2.5">
                    <ToneBadge
                      tone={item.action === 'increase' ? 'success' : 'warning'}
                      label={item.action === 'increase' ? '增加帧' : '减少帧'}
                    />
                  </td>
                  <td className="px-4 py-2.5 font-mono text-ink-secondary">{item.weight}</td>
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={() => toggleMutation.run({ id: item.id, enabled: !item.enabled }).then(() => query.refetch())}
                      disabled={toggleMutation.loading}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-60 ${
                        item.enabled ? 'bg-success' : 'bg-line'
                      }`}
                      aria-label={item.enabled ? '停用' : '启用'}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${item.enabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
                    </button>
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">{item.platform_scope ?? '全部'}</td>
                  <td className="px-4 py-2.5 text-xs text-ink-muted">{formatDateTime(item.created_at)}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex justify-end gap-1">
                      <button type="button" onClick={() => openEdit(item)} className="rounded-md p-1.5 text-ink-muted transition-colors hover:bg-sidebar hover:text-primary" aria-label="编辑">
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button type="button" onClick={() => setDeleteTarget(item)} className="rounded-md p-1.5 text-ink-muted transition-colors hover:bg-sidebar hover:text-danger" aria-label="删除">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 新增/编辑弹窗 */}
      <Modal
        open={formOpen}
        title={editing ? '编辑词条' : '新增词条'}
        onClose={() => setFormOpen(false)}
        footer={
          <>
            <button type="button" onClick={() => setFormOpen(false)} className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar">
              取消
            </button>
            <button type="button" onClick={submit} disabled={saving} className="rounded-md bg-primary px-3 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover disabled:opacity-60">
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
              <input type="number" step="0.1" min="0.1" value={form.weight} onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })} className={inputClass} />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-ink">生效平台（可空=全部）</label>
            <input value={form.platform_scope} onChange={(e) => setForm({ ...form, platform_scope: e.target.value })} placeholder="如 douyin / bilibili" className={inputClass} />
          </div>
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
