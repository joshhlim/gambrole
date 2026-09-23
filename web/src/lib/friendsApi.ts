"use client";

import { post, request } from "./api";
import type { FriendsResponse, MyProfile, UserProfile } from "./friendsTypes";

const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export const friendsApi = {
  /** Also registers you in the directory — see the Python route. */
  me: () => request<MyProfile>("/users/me"),
  setUsername: (username: string) =>
    request<{ username: string }>("/users/me/username", {
      method: "PUT",
      body: JSON.stringify({ username }),
    }),
  /** Pre-signup check — works logged out, which is what lets the form
   * refuse a taken handle before the account is created. */
  usernameAvailable: (u: string) =>
    request<{ available: boolean; reason: string | null; username?: string }>(
      `/users/username-available?u=${encodeURIComponent(u)}`,
    ),
  search: (q: string) =>
    request<{ results: UserProfile[] }>(`/users/search?q=${encodeURIComponent(q)}`),
  list: () => request<FriendsResponse>("/friends"),
  suggestions: () => request<{ results: UserProfile[] }>("/friends/suggestions"),
  sendRequest: (userId: string) =>
    post<{ status: "pending" | "accepted" }>("/friends/requests", { user_id: userId }),
  accept: (edgeId: string) => post<{ status: string }>(`/friends/requests/${edgeId}/accept`),
  dismiss: (edgeId: string) => del<{ status: string }>(`/friends/requests/${edgeId}`),
  remove: (userId: string) => del<{ status: string }>(`/friends/${userId}`),
};
