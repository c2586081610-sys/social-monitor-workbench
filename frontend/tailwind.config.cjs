/** @type {import('tailwindcss').Config} */
// 设计 Token 唯一落地处：docs/design-tokens.json → Tailwind theme.extend。
// 前端代码禁止裸 hex/裸色值，一律引用以下语义类（bg-canvas / text-ink / border-line ...）。
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F8FAFC',            // color.bg.default 页面背景
        surface: '#FFFFFF',           // color.bg.surface 卡片/面板
        sidebar: '#F1F5F9',           // color.bg.sidebar 侧边栏
        ink: {
          DEFAULT: '#0F172A',         // color.text.primary
          secondary: '#475569',       // color.text.secondary
          muted: '#94A3B8',           // color.text.muted
        },
        line: '#E2E8F0',              // color.border
        primary: {
          DEFAULT: '#2563EB',         // color.primary
          hover: '#1D4ED8',           // color.primary.hover
          light: '#EFF6FF',
        },
        success: {
          DEFAULT: '#16A34A',         // color.success
          light: '#F0FDF4',
        },
        warning: {
          DEFAULT: '#D97706',         // color.warning
          light: '#FFFBEB',
        },
        danger: {
          DEFAULT: '#DC2626',         // color.danger
          light: '#FEF2F2',
        },
        info: {
          DEFAULT: '#0891B2',         // color.info
          light: '#ECFEFF',
        },
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'PingFang SC',
          'Microsoft YaHei',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SF Mono', 'Cascadia Code', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(0 0 0 / 0.05)',   // shadow.sm
        panel: '0 4px 6px -1px rgb(0 0 0 / 0.1)', // shadow.md
      },
      borderRadius: {
        sm: '0.25rem',
        md: '0.375rem',
        lg: '0.5rem',
        full: '9999px',
      },
    },
  },
  plugins: [],
};
