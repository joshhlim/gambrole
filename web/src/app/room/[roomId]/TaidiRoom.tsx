"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { usePolling } from "@/lib/usePolling";
import { readFreshState } from "@/lib/freshState";
import type { GameRules, RoomState } from "@/lib/types";

/** Rules chosen on /new before the room existed — see that page for why
 * this can't just be sent at room-creation time. */
function readStoredRules(roomId: string): Partial<GameRules> | undefined {
  try {
    const raw = sessionStorage.getItem(`gambrole_rules_${roomId}`);
    return raw ? (JSON.parse(raw) as GameRules) : undefined;
  } catch {
    return undefined;
  }
}

function money(cents: number): string {
  const dollars = Math.abs(cents) / 100;
  return `${cents < 0 ? "-" : ""}$${dollars.toFixed(2)}`;
}

export default function TaidiRoom({ roomId, me }: { roomId: string; me: string }) {
  const router = useRouter();
  const [banner, setBanner] = useState<string | null>(null);
  const [cardsInput, setCardsInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [blockedBy, setBlockedBy] = useState<string | null>(null);
  const joinedRef = useRef(false);

  const { data: state, setData } = usePolling<RoomState>(
    () => api.getState(roomId),
    1500,
    [roomId, me],
    readFreshState<RoomState>(roomId),
  );

  const isMember = !!(state && me in state.members);

  useEffect(() => {
    // The host disbanded the room while others were still in the lobby —
    // everyone still viewing it gets bounced home on their next poll.
    if (state?.status === "disbanded") router.replace("/");
  }, [state?.status, router]);

  // Auto-join once: if we landed here via a shared link/code without having
  // joined yet, and the room is still in its lobby, join automatically.
  useEffect(() => {
    if (!state || joinedRef.current) return;
    if (!isMember && state.status === "lobby") {
      joinedRef.current = true;
      api
        .join(roomId)
        .then(setData)
        .catch((e) => {
          setBanner(e instanceof ApiError ? e.message : "Couldn't join this room.");
          // Refused because you're already in another room: the API hands
          // back which one, so offer a way there instead of stranding you
          // on a lobby you can't enter.
          const other = (e instanceof ApiError ? e.detail : null) as {
            active_room_id?: string;
          } | null;
          if (other?.active_room_id) setBlockedBy(other.active_room_id);
        });
    }
  }, [state, isMember, roomId, setData]);

  /**
   * Runs a command against the room's current seq. A 409 means someone
   * else's event landed first — that doesn't invalidate what THIS player
   * is trying to do (their own card count, a special-hand claim, ...), so
   * we resync to the fresh state and retry once against the new seq before
   * giving up. Only a second failure (or a non-seq error) surfaces to the
   * player.
   */
  async function run<T>(action: (seq: number) => Promise<T>) {
    setBusy(true);
    setBanner(null);
    let seq = state?.seq;
    for (let attempt = 0; attempt < 2; attempt++) {
      if (seq === undefined) break;
      try {
        const result = await action(seq);
        setBusy(false);
        return result;
      } catch (e) {
        if (e instanceof ApiError && e.conflict) {
          setData(e.conflict.state);
          seq = e.conflict.state.seq;
          continue; // retry once against the fresh seq
        }
        setBanner(e instanceof ApiError ? e.message : "Something went wrong.");
        setBusy(false);
        return null;
      }
    }
    setBanner("Someone else keeps acting first — try again.");
    setBusy(false);
    return null;
  }

  const membersBySeat = useMemo(
    () => (state ? Object.values(state.members).sort((a, b) => a.seat - b.seat) : []),
    [state],
  );
  const standings = useMemo(
    () => (state ? Object.entries(state.balances).sort(([, a], [, b]) => b - a) : []),
    [state],
  );
  const currentRound = state && state.rounds.length > 0 ? state.rounds[state.rounds.length - 1] : null;

  if (!state) {
    return <main className="flex-1 flex items-center justify-center text-muted text-sm">Loading…</main>;
  }

  const isHost = state.host_id === me;
  // Someone who stepped out keeps their balance and their place in the
  // standings, so fall back to the name recorded when they left.
  const nameOf = (id: string) =>
    state.members[id]?.display_name ?? state.departed?.[id] ?? "?";

  /**
   * Back minimises rather than leaves: you stay in the room and can use the
   * rest of the app, with home's "Rejoin Room" button as the way in again.
   * Actually leaving is a separate, explicit choice — see the Leave control
   * in the lobby and at the table.
   */
  function handleBack() {
    router.push("/");
  }

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={handleBack}
          disabled={busy}
          data-testid="back-btn"
          className="h-11 w-11 rounded-full border border-border flex items-center justify-center text-lg font-bold text-brand disabled:opacity-50"
        >
          ←
        </button>
      </div>

      {banner && (
        <div className="mb-4 rounded-lg border border-border bg-surface px-4 py-2 text-sm text-muted">
          {banner}
          {blockedBy && (
            <button
              onClick={() => router.push(`/room/${blockedBy}`)}
              data-testid="go-to-active-room-btn"
              className="mt-2 w-full rounded-lg bg-brand-strong py-2 text-xs font-semibold text-white"
            >
              Go to your game
            </button>
          )}
        </div>
      )}

      {state.status === "lobby" && (
        <Lobby
          state={state}
          isHost={isHost}
          isMember={isMember}
          canJoin={!blockedBy}
          membersBySeat={membersBySeat}
          busy={busy}
          onJoin={() => run((_seq) => api.join(roomId)).then((r) => r && setData(r))}
          onStart={() =>
            run((seq) => api.start(roomId, seq, readStoredRules(roomId))).then((r) => r && setData(r))
          }
          onLeave={() => run((seq) => api.leave(roomId, seq)).then((r) => r && router.push("/"))}
          onDisband={() =>
            run((seq) => api.disband(roomId, seq)).then((r) => r && router.push("/"))
          }
        />
      )}

      {state.status === "in_progress" && currentRound && (
        <TableView
          state={state}
          me={me}
          currentRound={currentRound}
          standings={standings}
          nameOf={nameOf}
          busy={busy}
          cardsInput={cardsInput}
          setCardsInput={setCardsInput}
          onClaimWin={() => run((seq) => api.claimWin(roomId, seq)).then((r) => r && setData(r))}
          onSubmitCards={(cards) =>
            run((seq) => api.submitCards(roomId, seq, cards)).then((r) => {
              if (r) {
                setData(r);
                setCardsInput("");
              }
            })
          }
          isHost={isHost}
          onSpecialHand={() =>
            run((seq) => api.specialHand(roomId, seq)).then((r) => r && setData(r))
          }
          onVoidRound={() =>
            run((seq) => api.voidLastRound(roomId, seq)).then((r) => r && setData(r))
          }
          onVoidSpecial={() =>
            run((seq) => api.voidSpecialHand(roomId, seq)).then((r) => r && setData(r))
          }
          onStepOut={() => run((seq) => api.stepOut(roomId, seq)).then((r) => r && router.push("/"))}
          onEndGame={() => run((seq) => api.endGame(roomId, seq)).then((r) => r && setData(r))}
        />
      )}

      {state.status === "ended" && (
        <div className="space-y-6">
          <EndedView
            standings={standings}
            nameOf={nameOf}
            roundsPlayed={state.rounds.length}
            onHome={() => router.push("/")}
          />
          <RoundLog rounds={state.rounds} me={me} nameOf={nameOf} />
        </div>
      )}
    </main>
  );
}

function Lobby({
  state,
  isHost,
  isMember,
  canJoin,
  membersBySeat,
  busy,
  onJoin,
  onStart,
  onLeave,
  onDisband,
}: {
  state: RoomState;
  isHost: boolean;
  isMember: boolean;
  canJoin: boolean;
  membersBySeat: RoomState["members"][string][];
  busy: boolean;
  onJoin: () => void;
  onStart: () => void;
  onLeave: () => void;
  onDisband: () => void;
}) {
  const [confirmDisband, setConfirmDisband] = useState(false);
  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-xs uppercase tracking-widest text-muted mb-1">Room code</p>
        <p data-testid="invite-code" className="text-3xl font-extrabold tracking-[0.3em] text-brand">{state.invite_code}</p>
      </div>

      <div>
        <p className="text-xs uppercase tracking-widest text-muted mb-2">Players</p>
        <div className="space-y-2">
          {membersBySeat.map((m) => (
            <div
              key={m.player_id}
              data-testid="lobby-member"
              className="rounded-xl border border-border bg-surface px-4 py-3 text-sm font-medium"
            >
              {m.display_name}
              {m.player_id === state.host_id && <span className="ml-2 text-xs text-gold">HOST</span>}
            </div>
          ))}
        </div>
      </div>

      {!isMember ? (
        // Hidden when you're already in another room — the API would refuse
        // every tap, so showing it just invites a button that always fails.
        canJoin ? (
          <button
            onClick={onJoin}
            disabled={busy}
            data-testid="lobby-join-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Join Room
          </button>
        ) : null
      ) : isHost ? (
        <div className="space-y-3">
          <button
            onClick={onStart}
            disabled={busy || membersBySeat.length < 2}
            data-testid="start-game-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            {membersBySeat.length < 2 ? "Waiting for more players…" : "Start Game"}
          </button>
          {confirmDisband ? (
            <div className="flex gap-2">
              <button
                onClick={onDisband}
                disabled={busy}
                data-testid="confirm-disband-btn"
                className="flex-1 rounded-xl bg-danger py-2.5 text-xs font-semibold text-white disabled:opacity-50"
              >
                Close for everyone
              </button>
              <button
                onClick={() => setConfirmDisband(false)}
                data-testid="cancel-disband-btn"
                className="flex-1 rounded-xl border border-border py-2.5 text-xs font-semibold text-muted"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDisband(true)}
              disabled={busy}
              data-testid="disband-room-btn"
              className="w-full rounded-xl border border-border py-2.5 text-xs font-semibold text-muted disabled:opacity-50"
            >
              Close Room
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-center text-sm text-muted">Waiting for the host to start…</p>
          <button
            onClick={onLeave}
            disabled={busy}
            data-testid="leave-room-btn"
            className="w-full rounded-xl border border-border py-2.5 text-xs font-semibold text-muted disabled:opacity-50"
          >
            Leave Room
          </button>
        </div>
      )}
    </div>
  );
}

/** An openable record of what happened, round by round.
 *
 * Deliberately not a full breakdown: enough to answer "wait, what did I get
 * charged for?" at the table without anyone scrolling through a ledger.
 * Everything here is already in the folded state — no extra request. */
function RoundLog({
  rounds,
  me,
  nameOf,
}: {
  rounds: RoomState["rounds"];
  me: string;
  nameOf: (id: string) => string;
}) {
  const [open, setOpen] = useState(false);
  // Only rounds where something actually happened, newest first.
  const played = rounds.filter((r) => r.transfers.length > 0 || r.winner).reverse();
  if (played.length === 0) return null;

  return (
    <div className="rounded-xl border border-border bg-surface">
      <button
        onClick={() => setOpen(!open)}
        data-testid="round-log-toggle"
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-semibold text-muted"
      >
        <span>Round log ({played.length})</span>
        <span aria-hidden>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div data-testid="round-log" className="space-y-3 border-t border-border px-4 py-3">
          {played.map((r) => {
            const net = r.transfers.reduce(
              (a, t) => a + (t.to_player === me ? t.amount_cents : 0) - (t.from_player === me ? t.amount_cents : 0),
              0,
            );
            const specials = Object.entries(r.special_counts).filter(([, n]) => n > 0);
            return (
              <div key={r.round_no} data-testid={`round-log-${r.round_no}`} className="space-y-1">
                <div className="flex items-baseline justify-between">
                  <p className="text-xs font-semibold text-foreground">
                    Round {r.round_no}
                    {r.winner ? ` · ${nameOf(r.winner)} won` : " · unfinished"}
                  </p>
                  <span className={`text-xs font-bold ${net < 0 ? "text-danger" : "text-brand-strong"}`}>
                    {money(net)}
                  </span>
                </div>
                {Object.keys(r.cards_submitted).length > 0 && (
                  <p className="text-[11px] text-muted">
                    {Object.entries(r.cards_submitted)
                      .map(([pid, c]) => `${nameOf(pid)} ${c}`)
                      .join(" · ")}
                  </p>
                )}
                {specials.length > 0 && (
                  <p className="text-[11px] text-muted">
                    Special: {specials.map(([pid, n]) => `${nameOf(pid)}${n > 1 ? ` x${n}` : ""}`).join(", ")}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function TableView({
  state,
  me,
  currentRound,
  standings,
  nameOf,
  busy,
  cardsInput,
  setCardsInput,
  onClaimWin,
  onSubmitCards,
  onSpecialHand,
  onVoidRound,
  onVoidSpecial,
  onStepOut,
  onEndGame,
  isHost,
}: {
  state: RoomState;
  me: string;
  currentRound: NonNullable<RoomState["rounds"][number]>;
  standings: [string, number][];
  nameOf: (id: string) => string;
  busy: boolean;
  cardsInput: string;
  setCardsInput: (v: string) => void;
  onClaimWin: () => void;
  onSubmitCards: (cards: number) => void;
  onSpecialHand: () => void;
  onVoidRound: () => void;
  onVoidSpecial: () => void;
  onStepOut: () => void;
  onEndGame: () => void;
  isHost: boolean;
}) {
  const [confirmSpecial, setConfirmSpecial] = useState(false);
  const [confirmVoid, setConfirmVoid] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const mySpecials = currentRound.special_counts[me] ?? 0;
  const isPlaying = currentRound.phase === "playing";
  const isCollecting = currentRound.phase === "collecting";
  const iAmWinner = currentRound.winner === me;
  const haveSubmitted = me in currentRound.cards_submitted;
  const pending = Object.keys(state.members).filter(
    (id) => id !== currentRound.winner && !(id in currentRound.cards_submitted),
  );

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-widest text-muted mb-2">
          Round {currentRound.round_no}
        </p>
        <div className="space-y-2">
          {standings.map(([playerId, cents], idx) => (
            <div
              key={playerId}
              data-testid="standing-row"
              data-player={nameOf(playerId)}
              className={`flex items-center justify-between rounded-xl border px-4 py-3 text-sm ${
                idx === 0 ? "border-gold bg-[#FFF8E1]" : "border-border bg-surface"
              }`}
            >
              <span className="font-medium">{nameOf(playerId)}</span>
              <span data-testid="standing-amount" className={`font-bold ${cents < 0 ? "text-danger" : "text-brand-strong"}`}>
                {money(cents)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {isPlaying && (
        <div className="space-y-3">
          <button
            onClick={onClaimWin}
            disabled={busy}
            data-testid="win-btn"
            className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
          >
            Win
          </button>
          {state.rules?.special_hands_enabled &&
            (confirmSpecial ? (
              // A special settles instantly and charges everyone else, so a
              // stray tap costs real money — make it deliberate.
              <div className="space-y-2 rounded-xl border border-brand-strong bg-[#FFF8E1] px-3 py-2.5">
                <p className="text-center text-xs text-brand">
                  Charge everyone else for a special hand?
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      setConfirmSpecial(false);
                      onSpecialHand();
                    }}
                    disabled={busy}
                    data-testid="confirm-special-btn"
                    className="flex-1 rounded-xl bg-brand py-2.5 text-xs font-semibold text-white disabled:opacity-50"
                  >
                    Claim it
                  </button>
                  <button
                    onClick={() => setConfirmSpecial(false)}
                    data-testid="cancel-special-btn"
                    className="flex-1 rounded-xl border border-border py-2.5 text-xs font-semibold text-muted"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmSpecial(true)}
                disabled={busy}
                data-testid="special-hand-btn"
                className="w-full rounded-xl border border-border py-3 text-sm font-semibold text-brand disabled:opacity-50"
              >
                Special Hand
              </button>
            ))}

        </div>
      )}

      {isCollecting && iAmWinner && (
        <p data-testid="waiting-text" className="text-center text-sm text-muted">
          Waiting for {pending.map(nameOf).join(", ")}…
        </p>
      )}

      {isCollecting && !iAmWinner && !haveSubmitted && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const n = Number(cardsInput);
            // 0 is the winner's count — the engine rejects it, so don't
            // let the form send it in the first place.
            if (Number.isInteger(n) && n >= 1) onSubmitCards(n);
          }}
          className="space-y-3"
        >
          <p className="text-sm text-center text-muted">
            {nameOf(currentRound.winner ?? "")} won — how many cards were you left with?
          </p>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            data-testid="cards-input"
            className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-center text-lg outline-none focus:border-brand-strong"
            value={cardsInput}
            onChange={(e) => setCardsInput(e.target.value)}
            autoFocus
          />
          <button
            type="submit"
            disabled={busy || cardsInput.trim() === "" || Number(cardsInput) < 1}
            data-testid="submit-cards-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Submit
          </button>
        </form>
      )}

      {isCollecting && !iAmWinner && haveSubmitted && (
        <p data-testid="waiting-text" className="text-center text-sm text-muted">
          Waiting for {pending.map(nameOf).join(", ")}…
        </p>
      )}

      <RoundLog rounds={state.rounds} me={me} nameOf={nameOf} />

      {/* Everything below here either reverses something or ends the
          night. Grouped, small and confirm-gated, kept well away from Win
          and Special — the buttons people reach for mid-hand. */}
      {(mySpecials > 0 || (isCollecting && (isHost || iAmWinner))) && (
        <div className="space-y-2 rounded-xl border border-border bg-surface px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wider text-muted">Fix a mistake</p>

        {/* Voiding a round deliberately leaves specials alone, so this is
            the only way back from a mistaken claim. */}
        {mySpecials > 0 && (
          <button
            onClick={onVoidSpecial}
            disabled={busy}
            data-testid="undo-special-btn"
            className="w-full rounded-lg border border-border py-2 text-xs font-semibold text-muted disabled:opacity-50"
          >
            Undo my special hand{mySpecials > 1 ? ` (${mySpecials})` : ""}
          </button>
        )}

        {/* The claimer can take back their own misclick; the host can too,
            as the backstop for when that player has gone quiet and the
            round would otherwise sit in `collecting` forever. */}
        {isCollecting &&
          (isHost || iAmWinner) &&
          (confirmVoid ? (
            <div className="space-y-2">
              <p className="text-center text-xs text-muted">
                Restart this round? Card counts so far are discarded.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setConfirmVoid(false);
                    onVoidRound();
                  }}
                  disabled={busy}
                  data-testid="confirm-void-btn"
                  className="flex-1 rounded-lg bg-danger py-2 text-xs font-semibold text-white disabled:opacity-50"
                >
                  Restart round
                </button>
                <button
                  onClick={() => setConfirmVoid(false)}
                  data-testid="cancel-void-btn"
                  className="flex-1 rounded-lg border border-border py-2 text-xs font-semibold text-muted"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setConfirmVoid(true)}
              disabled={busy}
              data-testid="void-round-btn"
              className="w-full rounded-lg border border-border py-2 text-xs font-semibold text-muted disabled:opacity-50"
            >
              Undo win claim
            </button>
          ))}
        </div>
      )}

      {/* Ending settles every balance and creates debts in the Debts tab,
          so it asks first and only the host sees it. Not filed under "fix a
          mistake" — it isn't one. */}
      <div className="rounded-xl border border-border bg-surface px-3 py-2.5">
        {isHost &&
          (confirmEnd ? (
            <div className="space-y-2">
              <p className="text-center text-xs text-muted">
                End the game and settle up? This can&apos;t be undone.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setConfirmEnd(false);
                    onEndGame();
                  }}
                  disabled={busy}
                  data-testid="confirm-end-btn"
                  className="flex-1 rounded-lg bg-danger py-2 text-xs font-semibold text-white disabled:opacity-50"
                >
                  End &amp; settle
                </button>
                <button
                  onClick={() => setConfirmEnd(false)}
                  data-testid="cancel-end-btn"
                  className="flex-1 rounded-lg border border-border py-2 text-xs font-semibold text-muted"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setConfirmEnd(true)}
              disabled={busy}
              data-testid="end-game-btn"
              className="w-full rounded-lg border border-border py-2 text-xs font-semibold text-muted disabled:opacity-50"
            >
              End Game
            </button>
          ))}
        {!isHost && (
          <p className="text-center text-[11px] text-muted">
            Only {nameOf(state.host_id)} can end the game.
          </p>
        )}

        {/* Leaving for good, as opposed to the back arrow, which just
            minimises. One-way: the engine refuses mid-game joins, so the
            confirm has to say so plainly. */}
        {confirmLeave ? (
          <div className="mt-2 space-y-2">
            <p className="text-center text-xs text-muted">
              Leave for good? You keep what you&apos;re up or down and settle with everyone,
              but you can&apos;t rejoin this game.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  setConfirmLeave(false);
                  onStepOut();
                }}
                disabled={busy}
                data-testid="confirm-leave-btn"
                className="flex-1 rounded-lg bg-danger py-2 text-xs font-semibold text-white disabled:opacity-50"
              >
                Leave game
              </button>
              <button
                onClick={() => setConfirmLeave(false)}
                data-testid="cancel-leave-btn"
                className="flex-1 rounded-lg border border-border py-2 text-xs font-semibold text-muted"
              >
                Stay
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setConfirmLeave(true)}
            disabled={busy}
            data-testid="leave-game-btn"
            className="mt-2 w-full rounded-lg border border-border py-2 text-xs font-semibold text-muted disabled:opacity-50"
          >
            Leave game
          </button>
        )}
      </div>
    </div>
  );
}

function EndedView({
  standings,
  nameOf,
  roundsPlayed,
  onHome,
}: {
  standings: [string, number][];
  nameOf: (id: string) => string;
  roundsPlayed: number;
  onHome: () => void;
}) {
  const [topId, topCents] = standings[0] ?? [null, 0];

  return (
    <div className="space-y-6">
      <div className="text-center space-y-1">
        <p data-testid="game-over" className="text-lg font-extrabold text-brand">
          Game Over
        </p>
        <p className="text-xs uppercase tracking-widest text-muted">
          {roundsPlayed} round{roundsPlayed === 1 ? "" : "s"} played
        </p>
      </div>

      {topId && (
        <p className="text-center text-sm text-muted">
          <span className="font-semibold text-foreground">{nameOf(topId)}</span> wins with{" "}
          <span className="font-bold text-brand-strong">{money(topCents)}</span>
        </p>
      )}

      <div className="space-y-2">
        {standings.map(([playerId, cents], idx) => (
          <div
            key={playerId}
            data-testid="standing-row"
            data-player={nameOf(playerId)}
            className={`flex items-center justify-between rounded-xl border px-4 py-3 text-sm ${
              idx === 0 ? "border-gold bg-[#FFF8E1]" : "border-border bg-surface"
            }`}
          >
            <span className="font-medium">{nameOf(playerId)}</span>
            <span
              data-testid="standing-amount"
              className={`font-bold ${cents < 0 ? "text-danger" : "text-brand-strong"}`}
            >
              {money(cents)}
            </span>
          </div>
        ))}
      </div>
      <button
        onClick={onHome}
        data-testid="back-to-home-btn"
        className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white"
      >
        Back to Home
      </button>
    </div>
  );
}
