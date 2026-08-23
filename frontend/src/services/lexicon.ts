/** 词库资源 API 封装（对齐 openapi: lexicon）。 */
import { deleteJson, getJson, patchJson, postJson } from './http';
import type { LexiconCreate, LexiconItem, LexiconList, LexiconUpdate } from '../types/api.d';

export function listLexicon(): Promise<LexiconList> {
  return getJson<LexiconList>('/api/v1/lexicon');
}

export function createLexiconEntry(body: LexiconCreate): Promise<LexiconItem> {
  return postJson<LexiconItem>('/api/v1/lexicon', body);
}

export function updateLexiconEntry(id: number, body: LexiconUpdate): Promise<LexiconItem> {
  return patchJson<LexiconItem>(`/api/v1/lexicon/${id}`, body);
}

export function deleteLexiconEntry(id: number): Promise<{ deleted: boolean }> {
  return deleteJson<{ deleted: boolean }>(`/api/v1/lexicon/${id}`);
}
