"use client";

import { request } from "./api";
import type { StatsResponse } from "./statsTypes";

export const statsApi = {
  getMine: () => request<StatsResponse>("/stats/me"),
};
