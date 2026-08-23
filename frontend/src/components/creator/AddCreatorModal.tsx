/** 添加博主弹窗（P9）：平台 / 主页链接 / 博主名 / 分组 / 轮询间隔 / 最低画质开关。 */
import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import Modal from '../common/Modal';
import { createCreator } from '../../services/creators';
import { useMutation } from '../../hooks/useApi';
import { PLATFORMS } from '../../utils/constants';
import type { Group, Platform } from '../../types/api.d';

interface AddCreatorModalProps {
  open: boolean;
  groups: Group[];
  onClose: () => void;
  onCreated: () => void;
}

const DEFAULT_INTERVAL: Record<string, number> = { douyin: 10, bilibili: 5, xhs: 5, twitter: 5 };

export default function AddCreatorModal({ open, groups, onClose, onCreated }: AddCreatorModalProps) {
  const [platform, setPlatform] = useState<Platform>('douyin');
  const [name, setName] = useState('');
  const [profileUrl, setProfileUrl] = useState('');
  const [externalId, setExternalId] = useState('');
  const [groupId, setGroupId] = useState<number | null>(null);
  const [pollInterval, setPollInterval] = useState(DEFAULT_INTERVAL.douyin);
  const [lowestQuality, setLowestQuality] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation(() =>
    createCreator({
      platform,
      name: name.trim(),
      profile_url: profileUrl.trim(),
      external_id: externalId.trim(),
      group_id: groupId,
    }),
  );

  useEffect(() => {
    if (!open) return;
    setPlatform('douyin');
    setName('');
    setProfileUrl('');
    setExternalId('');
    setGroupId(null);
    setPollInterval(DEFAULT_INTERVAL.douyin);
    setLowestQuality(true);
    setError(null);
  }, [open]);

  const handlePlatformChange = (p: Platform) => {
    setPlatform(p);
    setPollInterval(DEFAULT_INTERVAL[p] ?? 5);
  };

  const submit = async () => {
    setError(null);
    if (!name.trim()) return setError('请填写博主名');
    if (!profileUrl.trim()) return setError('请填写主页链接');
    if (!externalId.trim()) return setError('请填写平台唯一 ID（主页链接中可提取）');
    try {
      await mutation.run();
      onCreated();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '添加失败';
      setError(msg.includes('409') || msg.includes('CONFLICT') ? '该博主已存在（平台 + ID 重复）' : msg);
    }
  };

  const inputClass =
    'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none';

  return (
    <Modal
      open={open}
      title="添加博主"
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-secondary transition-colors hover:bg-sidebar"
          >
            取消
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={mutation.loading}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-white transition-colors hover:bg-primary-hover disabled:opacity-60"
          >
            <Plus className="h-4 w-4" />
            {mutation.loading ? '添加中…' : '添加'}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-ink">平台</label>
          <div className="grid grid-cols-4 gap-2">
            {PLATFORMS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => handlePlatformChange(p.value)}
                className={`rounded-md border px-2 py-2 text-sm transition-colors ${
                  platform === p.value
                    ? 'border-primary bg-primary-light text-primary'
                    : 'border-line bg-surface text-ink-secondary hover:bg-sidebar'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="add-name" className="mb-1 block text-sm font-medium text-ink">博主名</label>
          <input id="add-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：张三" className={inputClass} />
        </div>

        <div>
          <label htmlFor="add-url" className="mb-1 block text-sm font-medium text-ink">主页链接</label>
          <input
            id="add-url"
            value={profileUrl}
            onChange={(e) => setProfileUrl(e.target.value)}
            placeholder="https://…"
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor="add-ext" className="mb-1 block text-sm font-medium text-ink">平台唯一 ID</label>
          <input
            id="add-ext"
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
            placeholder="sec_uid / uid / user_id / handle"
            className={inputClass}
          />
          <p className="mt-1 text-xs text-ink-muted">通常可在主页链接中提取（幂等去重依据）。</p>
        </div>

        <div>
          <label htmlFor="add-group" className="mb-1 block text-sm font-medium text-ink">分组</label>
          <select
            id="add-group"
            value={groupId ?? ''}
            onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : null)}
            className={inputClass}
          >
            <option value="">未分组</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="add-interval" className="mb-1 block text-sm font-medium text-ink">轮询间隔（分钟）</label>
            <input
              id="add-interval"
              type="number"
              min={1}
              value={pollInterval}
              onChange={(e) => setPollInterval(Number(e.target.value))}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-ink">画质</label>
            <label className="flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm text-ink-secondary">
              <input
                type="checkbox"
                checked={lowestQuality}
                onChange={(e) => setLowestQuality(e.target.checked)}
                className="h-4 w-4 accent-primary"
              />
              最低画质（省流量）
            </label>
          </div>
        </div>

        <p className="rounded-md bg-sidebar px-3 py-2 text-xs leading-5 text-ink-muted">
          说明：P1 阶段轮询间隔与画质由监控层统一调度（RSSHub 5–10min / 抖音 ≥10min，下载最低画质），此处选择仅作记录展示。
        </p>

        {error ? <p className="text-sm text-danger">{error}</p> : null}
      </div>
    </Modal>
  );
}
