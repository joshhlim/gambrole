import type { GameType } from "./types";

// Every in-app page is one static file (the iOS app bundles the site as
// plain files), so ids travel in the query string, not the path.

export const roomHref = (roomId: string, game?: GameType | null) =>
  `/room?id=${encodeURIComponent(roomId)}${game ? `&g=${game}` : ""}`;

export const groupHref = (groupId: string) => `/group?id=${encodeURIComponent(groupId)}`;
