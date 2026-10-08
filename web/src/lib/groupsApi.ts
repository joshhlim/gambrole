"use client";

import { post, request } from "./api";
import type { GroupDetail, GroupSummary } from "./groupsTypes";

const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export const groupsApi = {
  list: () => request<{ groups: GroupSummary[] }>("/groups"),
  create: (name: string) => post<GroupDetail>("/groups", { name }),
  get: (groupId: string) => request<GroupDetail>(`/groups/${groupId}`),
  /** Idempotent — joining a group you're already in just returns it. */
  join: (code: string) => post<GroupDetail>(`/groups/join/${encodeURIComponent(code)}`),
  leave: (groupId: string) => post<{ left: true }>(`/groups/${groupId}/leave`),
  // Owner only from here down.
  rename: (groupId: string, name: string) =>
    request<GroupDetail>(`/groups/${groupId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  removeMember: (groupId: string, userId: string) =>
    del<GroupDetail>(`/groups/${groupId}/members/${userId}`),
  /** The old code (and every link carrying it) stops working. */
  rotateCode: (groupId: string) => post<GroupDetail>(`/groups/${groupId}/invite-code`),
  remove: (groupId: string) => del<{ deleted: true }>(`/groups/${groupId}`),
};

export const groupJoinUrl = (code: string) => `${window.location.origin}/groups/join/${code}`;
