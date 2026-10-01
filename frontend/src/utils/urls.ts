/** 外部平台链接只允许明确的 HTTP(S) scheme，避免把不可信文本放入 href。 */
export function safeHttpUrl(value?: string | null): string | null {
  if (!value?.trim()) return null;
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}
