"use client";

import { request } from "./api";
import type { HistoryResponse } from "./historyTypes";

export const historyApi = {
  getMine: () => request<HistoryResponse>("/history/me"),
};
