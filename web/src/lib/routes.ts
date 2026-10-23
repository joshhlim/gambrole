import type { GameType } from "./types";

// Every in-app page is one static file (the iOS app bundles the site as
// plain files), so ids travel in the query string, not the path.

export const roomHref = (roomId: string, game?: GameType | null) =>
  `/room?id=${encodeURIComponent(roomId)}${game ? `&g=${game}` : ""}`;

export const groupHref = (groupId: string) => `/group?id=${encodeURIComponent(groupId)}`;

/** Screens that take the whole display — a live table, a form you're in the
 * middle of, a link you followed. They have their own way out, so no tab
 * bar, and a live table refreshes itself, so no pull-to-refresh. */
const IMMERSIVE = ["/room", "/new", "/play/join", "/auth", "/claim", "/groups/join"];

export const isImmersive = (pathname: string) =>
  IMMERSIVE.some((p) => pathname === p || pathname.startsWith(`${p}/`));
