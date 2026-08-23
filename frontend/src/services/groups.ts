/** 分组资源 API 封装（对齐 openapi: groups）。 */
import { deleteJson, getJson, patchJson, postJson } from './http';
import type { DeleteResult, Group, GroupList } from '../types/api.d';

export function listGroups(): Promise<GroupList> {
  return getJson<GroupList>('/api/v1/groups');
}

export function createGroup(name: string): Promise<Group> {
  return postJson<Group>('/api/v1/groups', { name });
}

export function renameGroup(id: number, name: string): Promise<Group> {
  return patchJson<Group>(`/api/v1/groups/${id}`, { name });
}

export function deleteGroup(id: number): Promise<DeleteResult> {
  return deleteJson<DeleteResult>(`/api/v1/groups/${id}`);
}
