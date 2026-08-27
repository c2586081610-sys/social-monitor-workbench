/** 小型开关（role=switch）：纯 Tailwind Token，无 emoji；支持键盘可达（原生 button）。 */
interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** 无障碍标签（必填，供读屏朗读用途） */
  label: string;
  size?: 'sm' | 'md';
}

const TRACK: Record<'sm' | 'md', string> = {
  sm: 'h-4 w-7',
  md: 'h-5 w-8',
};

const KNOB: Record<'sm' | 'md', string> = {
  sm: 'h-3 w-3',
  md: 'h-4 w-4',
};

const KNOB_ON: Record<'sm' | 'md', string> = {
  sm: 'translate-x-3.5',
  md: 'translate-x-4',
};

export default function Toggle({ checked, onChange, disabled, label, size = 'md' }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex shrink-0 items-center rounded-full transition-colors duration-150 ${TRACK[size]} ${
        checked ? 'bg-primary' : 'bg-line'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
    >
      <span
        className={`inline-block transform rounded-full bg-surface shadow-card transition-transform duration-150 ${KNOB[size]} ${
          checked ? KNOB_ON[size] : 'translate-x-0.5'
        }`}
      />
    </button>
  );
}
