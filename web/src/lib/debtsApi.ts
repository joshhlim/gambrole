"use client";

import { post, request } from "./api";
import type { DebtActionResult, DebtsResponse } from "./debtsTypes";

export const debtsApi = {
  getMine: () => request<DebtsResponse>("/debts/me"),
  markPaid: (settlementId: string) =>
    post<DebtActionResult>(`/debts/${settlementId}/mark-paid`),
  approve: (settlementId: string) => post<DebtActionResult>(`/debts/${settlementId}/approve`),
  reject: (settlementId: string) => post<DebtActionResult>(`/debts/${settlementId}/reject`),
};
