"use client";

import { useEffect, useRef, useState } from "react";
import { Directory, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { money } from "@/lib/format";
import { hapticSuccess, isNativeApp } from "@/lib/native";
import type { GameType } from "@/lib/types";

/**
 * True only when the game ended while you were watching — not when you
 * open a finished game from your history. The status this page first saw
 * is the tell.
 */
export function useJustEnded(status: string | undefined): boolean {
  // The first status that actually arrived: a page still loading has none,
  // and an old game would otherwise look like it ended just now.
  const [firstSeen, setFirstSeen] = useState(status);
  if (firstSeen === undefined && status !== undefined) setFirstSeen(status);
  return firstSeen !== undefined && firstSeen !== "ended" && status === "ended";
}

/** The end of a game, felt: a success buzz for everyone at the table, and
 * confetti for whoever finished up. Renders nothing for an old game. */
export function EndMoment({ justEnded, won }: { justEnded: boolean; won: boolean }) {
  useEffect(() => {
    if (justEnded) hapticSuccess();
  }, [justEnded]);
  return justEnded && won ? <Confetti /> : null;
}

const CONFETTI_COLOURS = ["#eccd72", "#d9b44a", "#1e6b4f", "#5cc895", "#f7f5f0"];

/** A one-off burst from the top of the screen, gone in about three
 * seconds. Skipped for anyone who has asked their device for less motion. */
function Confetti() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDone(true);
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;
    el.width = w * dpr;
    el.height = h * dpr;
    ctx.scale(dpr, dpr);

    const pieces = Array.from({ length: 140 }, () => ({
      x: w / 2 + (Math.random() - 0.5) * w * 0.3,
      y: -10 - Math.random() * 40,
      vx: (Math.random() - 0.5) * 9,
      vy: Math.random() * 4 + 2,
      size: Math.random() * 6 + 5,
      spin: Math.random() * Math.PI,
      vspin: (Math.random() - 0.5) * 0.3,
      colour: CONFETTI_COLOURS[Math.floor(Math.random() * CONFETTI_COLOURS.length)],
    }));
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = now - start;
      ctx.clearRect(0, 0, w, h);
      ctx.globalAlpha = Math.max(0, 1 - Math.max(0, t - 1800) / 1200);
      for (const p of pieces) {
        p.vy += 0.18;
        p.vx *= 0.99;
        p.x += p.vx;
        p.y += p.vy;
        p.spin += p.vspin;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.spin);
        ctx.fillStyle = p.colour;
        ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
        ctx.restore();
      }
      if (t < 3000) frame = requestAnimationFrame(tick);
      else setDone(true);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  if (done) return null;
  return <canvas ref={canvas} aria-hidden className="pointer-events-none fixed inset-0 z-50 h-full w-full" />;
}

const GAME_LABEL: Record<GameType, string> = { taidi: "Taidi", mahjong: "Mahjong" };

export interface ResultsCard {
  game: GameType;
  /** "12 rounds" / "8 hands". */
  played: string;
  endedAt: string | null;
  standings: { name: string; cents: number }[];
}

/** The page's own display face, by the name next/font gave it, so the card
 * matches the app rather than falling back to a system font. */
function displayFont(): string {
  const family = getComputedStyle(document.documentElement).getPropertyValue("--font-outfit").trim();
  return family || "system-ui";
}

/** Draws the results as a square image for a chat: the app's green, the
 * standings, the winner in gold. */
async function drawCard(card: ResultsCard): Promise<HTMLCanvasElement> {
  await document.fonts.ready;
  const S = 1080;
  const c = document.createElement("canvas");
  c.width = S;
  c.height = S;
  const ctx = c.getContext("2d")!;
  const font = displayFont();

  const bg = ctx.createRadialGradient(S * 0.25, S * 0.15, 0, S * 0.5, S * 0.5, S * 0.9);
  bg.addColorStop(0, "#2a5141");
  bg.addColorStop(0.6, "#1e3a2f");
  bg.addColorStop(1, "#16291f");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, S, S);

  const pad = 90;
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#eccd72";
  ctx.font = `800 44px ${font}`;
  ctx.fillText("GamBROle", pad, pad + 30);

  ctx.fillStyle = "#f7f5f0";
  ctx.font = `800 84px ${font}`;
  ctx.fillText(`${GAME_LABEL[card.game]} night`, pad, 250);
  ctx.globalAlpha = 0.7;
  ctx.font = `500 36px ${font}`;
  const when = card.endedAt
    ? new Date(card.endedAt).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })
    : "";
  ctx.fillText([when, card.played].filter(Boolean).join(" · "), pad, 310);
  ctx.globalAlpha = 1;

  const rows = card.standings.slice(0, 6);
  const top = 400;
  const rowH = Math.min(100, (S - top - 150) / Math.max(rows.length, 1));
  rows.forEach((r, i) => {
    const y = top + i * rowH;
    if (i === 0) {
      ctx.fillStyle = "rgba(236,205,114,0.14)";
      ctx.beginPath();
      ctx.roundRect(pad - 24, y - 10, S - 2 * pad + 48, rowH - 14, 22);
      ctx.fill();
    }
    ctx.fillStyle = i === 0 ? "#eccd72" : "#f7f5f0";
    ctx.font = `${i === 0 ? 800 : 600} 46px ${font}`;
    let name = r.name;
    while (ctx.measureText(name).width > S - 2 * pad - 300 && name.length > 2) name = name.slice(0, -2);
    if (name !== r.name) name += "…";
    ctx.fillText(name, pad, y + rowH / 2 + 8);
    ctx.textAlign = "right";
    ctx.fillStyle = r.cents > 0 ? "#5cc895" : r.cents < 0 ? "#ff8a7a" : "#f7f5f0";
    ctx.font = `800 46px ${font}`;
    ctx.fillText(`${r.cents > 0 ? "+" : ""}${money(r.cents)}`, S - pad, y + rowH / 2 + 8);
    ctx.textAlign = "left";
  });

  ctx.globalAlpha = 0.55;
  ctx.fillStyle = "#f7f5f0";
  ctx.font = `500 30px ${font}`;
  ctx.fillText("Game night, settled", pad, S - pad + 10);
  ctx.globalAlpha = 1;
  return c;
}

/** "Share results": the card as an image through the phone's share sheet
 * (a chat app is where game night gets argued about). */
export function ShareResultsButton({ card, className }: { card: ResultsCard; className: string }) {
  const [busy, setBusy] = useState(false);

  async function share() {
    setBusy(true);
    try {
      const canvas = await drawCard(card);
      const title = `${GAME_LABEL[card.game]} results`;
      if (isNativeApp()) {
        const data = canvas.toDataURL("image/png").split(",")[1];
        const file = await Filesystem.writeFile({
          path: `gambrole-results-${Date.now()}.png`,
          data,
          directory: Directory.Cache,
        });
        await Share.share({ title, files: [file.uri] });
        return;
      }
      const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
      if (!blob) return;
      const file = new File([blob], "gambrole-results.png", { type: "image/png" });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ title, files: [file] });
      } else {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = file.name;
        a.click();
        URL.revokeObjectURL(a.href);
      }
    } catch {
      // Dismissing the share sheet lands here too — not worth a message.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button type="button" onClick={share} disabled={busy} data-testid="share-results-btn" className={className}>
      {busy ? "Preparing…" : "Share results"}
    </button>
  );
}
