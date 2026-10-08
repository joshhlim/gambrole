"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { guestsApi } from "@/lib/guestsApi";
import { describeTaidiRules } from "@/lib/rulesSummary";
import type { AnyRoomState, Member, TaidiRoomState } from "@/lib/types";
import { useRoom } from "./useRoom";
import { PlayerLabel, RoomFrame, RoomLoading, RoomProblem, RulesLine, useRoomProfiles } from "./RoomShell";
import { useCurrencySymbol } from "@/lib/preferences";
import type { UserProfile } from "@/lib/friendsTypes";
import { ActingAs, AddGuestForm, GuestLinks, GuestTag } from "./Guests";

type RoomState = TaidiRoomState;

const narrow = (s: AnyRoomState) => (s.game_type === "taidi" ? s : null);

/** The round a command is about: the last one as this device saw it. */
const lastRoundNo = (s: RoomState) => s.rounds[s.rounds.length - 1]?.round_no ?? 0;

export default function TaidiRoom({
  roomId,
  me,
  initial,
  onWrongGame,
}: {
  roomId: string;
  me: string;
  initial: AnyRoomState | null;
  onWrongGame: (actual: AnyRoomState) => void;
}) {
  const router = useRouter();
  const [cardsInput, setCardsInput] = useState("");
  // Whose turn the host is entering (see ActingAs); null is the host.
  const [actorPick, setActorPick] = useState<string | null>(null);
  const { state, problem, isMember, isHost, busy, banner, blockedBy, run } = useRoom<RoomState>({
    roomId,
    me,
    narrow,
    join: useCallback((id: string) => api.join(id), []),
    initial,
    onWrongGame,
    movedOn: "That round already moved on.",
  });

  const membersBySeat = useMemo(
    () => (state ? Object.values(state.members).sort((a, b) => a.seat - b.seat) : []),
    [state],
  );
  const standings = useMemo(
    () => (state ? Object.entries(state.balances).sort(([, a], [, b]) => b - a) : []),
    [state],
  );
  const currentRound = state && state.rounds.length > 0 ? state.rounds[state.rounds.length - 1] : null;
  const guests = useMemo(() => membersBySeat.filter((m) => m.is_guest), [membersBySeat]);
  const profiles = useRoomProfiles(state);
  useCurrencySymbol();

  if (problem === "not-found" || problem === "forbidden") return <RoomProblem kind={problem} />;
  if (!state) return <RoomLoading offline={problem === "offline"} />;

  // Someone who stepped out keeps their balance and their place in the
  // standings, so fall back to the name recorded when they left.
  const nameOf = (id: string) =>
    state.members[id]?.display_name ?? state.departed?.[id] ?? "?";
  const rules = state.rules ?? state.draft_rules;
  // Only ever a guest still at the table, and only for the host: anything
  // else (a guest who stepped out, a stale pick) falls back to yourself.
  const actor = isHost && actorPick && state.members[actorPick]?.is_guest ? actorPick : me;
  const asPlayer = actor === me ? undefined : actor;
  // Every guest action hands the picker back to the host, so the next tap
  // can't land on a guest by accident.
  const done = (r: RoomState | null) => {
    if (r) setActorPick(null);
    return !!r;
  };

  return (
    <RoomFrame
      offline={problem === "offline"}
      banner={banner}
      blockedBy={blockedBy}
      groupId={state.group_id}
    >
      {state.status === "lobby" && (
        <Lobby
          state={state}
          isHost={isHost}
          isMember={isMember}
          canJoin={!blockedBy}
          membersBySeat={membersBySeat}
          profiles={profiles}
          busy={busy}
          rulesText={rules ? describeTaidiRules(rules) : null}
          onJoin={() => run(() => api.join(roomId))}
          onStart={() => run((s) => api.start(roomId, s.seq))}
          onLeave={() =>
            run((s) => api.leave(roomId, s.seq), { apply: false }).then((r) => r && router.push("/"))
          }
          onDisband={() =>
            run((s) => api.disband(roomId, s.seq), { apply: false }).then((r) => r && router.push("/"))
          }
          onAddGuest={(name) =>
            run((s) => guestsApi.add<RoomState>(roomId, "taidi", s.seq, name)).then((r) => !!r)
          }
          onRemoveGuest={(id) => run((s) => guestsApi.remove<RoomState>(roomId, "taidi", s.seq, id))}
        />
      )}

      {state.status === "in_progress" && currentRound && (
        <TableView
          state={state}
          me={me}
          isMember={isMember}
          currentRound={currentRound}
          standings={standings}
          nameOf={nameOf}
          profiles={profiles}
          busy={busy}
          cardsInput={cardsInput}
          setCardsInput={setCardsInput}
          guests={isHost ? guests : []}
          actor={actor}
          onPickActor={setActorPick}
          onClaimWin={() =>
            run((s) => api.claimWin(roomId, s.seq, lastRoundNo(s), asPlayer), { pinned: true }).then(done)
          }
          onSubmitCards={(cards) =>
            run((s) => api.submitCards(roomId, s.seq, lastRoundNo(s), cards), { pinned: true }).then(
              (r) => r && setCardsInput(""),
            )
          }
          onSubmitGuestCards={(guestId, cards) =>
            run((s) => api.submitCards(roomId, s.seq, lastRoundNo(s), cards, guestId), {
              pinned: true,
            }).then((r) => !!r)
          }
          isHost={isHost}
          onSpecialHand={() =>
            run((s) => api.specialHand(roomId, s.seq, lastRoundNo(s), asPlayer), { pinned: true }).then(
              done,
            )
          }
          onVoidRound={() =>
            run((s) => api.voidLastRound(roomId, s.seq, lastRoundNo(s)), { pinned: true })
          }
          onVoidSpecial={() =>
            run((s) => api.voidSpecialHand(roomId, s.seq, lastRoundNo(s), asPlayer), {
              pinned: true,
            }).then(done)
          }
          onStepOut={() =>
            // A guest stepping out leaves the host at the table; only your
            // own exit takes you home.
            asPlayer
              ? run((s) => api.stepOut(roomId, s.seq, asPlayer)).then(done)
              : run((s) => api.stepOut(roomId, s.seq), { apply: false }).then(
                  (r) => r && router.push("/"),
                )
          }
          onEndGame={() => run((s) => api.endGame(roomId, s.seq))}
        />
      )}

      {state.status === "ended" && (
        <div className="space-y-6">
          <EndedView
            standings={standings}
            nameOf={nameOf}
            profiles={profiles}
            roundsPlayed={state.rounds.length}
            onHome={() => router.push("/")}
          />
          {isHost && <GuestLinks roomId={roomId} />}
          <RoundLog rounds={state.rounds} me={me} nameOf={nameOf} />
        </div>
      )}
    </RoomFrame>
  );
}

function Lobby({
  state,
  isHost,
  isMember,
  canJoin,
  membersBySeat,
  profiles,
  busy,
  rulesText,
  onJoin,
  onStart,
  onLeave,
  onDisband,
  onAddGuest,
  onRemoveGuest,
}: {
  state: RoomState;
  isHost: boolean;
  isMember: boolean;
  canJoin: boolean;
  membersBySeat: Member[];
  profiles: Record<string, UserProfile>;
  busy: boolean;
  rulesText: string | null;
  onJoin: () => void;
  onStart: () => void;
  onLeave: () => void;
  onDisband: () => void;
  onAddGuest: (name: string) => Promise<boolean>;
  onRemoveGuest: (guestId: string) => void;
}) {
  const [confirmDisband, setConfirmDisband] = useState(false);
  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-xs uppercase tracking-widest text-muted mb-1">Room code</p>
        <p data-testid="invite-code" className="text-3xl font-extrabold tracking-[0.3em] text-brand">{state.invite_code}</p>
      </div>

      <RulesLine text={rulesText} />

      <div>
        <p className="text-xs uppercase tracking-widest text-muted mb-2">Players</p>
        <div className="space-y-2">
          {membersBySeat.map((m) => (
            <div
              key={m.player_id}
              data-testid="lobby-member"
              data-player={m.display_name}
              className="flex min-h-14 items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-sm font-medium"
            >
              <PlayerLabel playerId={m.player_id} name={m.display_name} profile={profiles[m.player_id]} link />
              {m.player_id === state.host_id && <span className="text-xs font-semibold text-gold-text">HOST</span>}
              {m.is_guest && <GuestTag />}
              {m.is_guest && isHost && (
                <button
                  type="button"
                  onClick={() => onRemoveGuest(m.player_id)}
                  disabled={busy}
                  data-testid="remove-guest-btn"
                  className="ml-auto shrink-0 text-xs font-semibold text-muted disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
        {isHost && isMember && (
          <div className="mt-3">
            <AddGuestForm busy={busy} onAdd={onAddGuest} />
          </div>
        )}
      </div>

      {!isMember ? (
        // Hidden when you're already in another room — the API would refuse
        // every tap, so showing it just invites a button that always fails.
        canJoin ? (
          <button
            onClick={onJoin}
            disabled={busy}
            data-testid="lobby-join-btn"
            className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary disabled:opacity-50"
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
            className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary disabled:opacity-50"
          >
            {membersBySeat.length < 2 ? "Waiting for more players…" : "Start Game"}
          </button>
          {confirmDisband ? (
            <div className="flex gap-2">
              <button
                onClick={onDisband}
                disabled={busy}
                data-testid="confirm-disband-btn"
                className="flex-1 rounded-xl bg-danger-fill py-2.5 text-xs font-semibold text-on-primary disabled:opacity-50"
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
  isMember,
  currentRound,
  standings,
  nameOf,
  profiles,
  busy,
  cardsInput,
  setCardsInput,
  guests,
  actor,
  onPickActor,
  onClaimWin,
  onSubmitCards,
  onSubmitGuestCards,
  onSpecialHand,
  onVoidRound,
  onVoidSpecial,
  onStepOut,
  onEndGame,
  isHost,
}: {
  state: RoomState;
  me: string;
  isMember: boolean;
  currentRound: NonNullable<RoomState["rounds"][number]>;
  standings: [string, number][];
  nameOf: (id: string) => string;
  profiles: Record<string, UserProfile>;
  busy: boolean;
  cardsInput: string;
  setCardsInput: (v: string) => void;
  /** Guests at the table — only ever non-empty for the host. */
  guests: Member[];
  /** Who Win / Special / Undo special / Leave act for (see ActingAs). */
  actor: string;
  onPickActor: (playerId: string) => void;
  onClaimWin: () => void;
  onSubmitCards: (cards: number) => void;
  onSubmitGuestCards: (guestId: string, cards: number) => Promise<boolean>;
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
  const forGuest = actor !== me;
  const actorName = nameOf(actor);
  const actorSpecials = currentRound.special_counts[actor] ?? 0;
  const isPlaying = currentRound.phase === "playing";
  const isCollecting = currentRound.phase === "collecting";
  const iAmWinner = currentRound.winner === me;
  const haveSubmitted = me in currentRound.cards_submitted;
  const pending = Object.keys(state.members).filter(
    (id) => id !== currentRound.winner && !(id in currentRound.cards_submitted),
  );
  // What the form would send, or null. A hand has 13 cards but the engine
  // accepts up to 52, so the form mirrors the engine rather than the deal.
  const cardsValue = /^\d+$/.test(cardsInput.trim()) ? Number(cardsInput.trim()) : null;
  const cardsValid = cardsValue !== null && cardsValue >= 1 && cardsValue <= 52;
  const guestsOwing = isCollecting
    ? guests.filter((g) => g.player_id !== currentRound.winner && !(g.player_id in currentRound.cards_submitted))
    : [];

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
              className={`flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-sm ${
                idx === 0 ? "border-gold bg-highlight" : "border-border bg-surface"
              }`}
            >
              <PlayerLabel playerId={playerId} name={nameOf(playerId)} profile={profiles[playerId]} />
              <span data-testid="standing-amount" className={`shrink-0 font-bold tabular ${cents < 0 ? "text-danger" : "text-brand-strong"}`}>
                {money(cents)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {state.rules && <RulesLine text={describeTaidiRules(state.rules)} />}

      {/* Someone watching without a seat (they stepped out) sees the table
          but gets nothing to press. */}
      {isMember && guests.length > 0 && (
        <ActingAs me={me} guests={guests} actor={actor} onPick={onPickActor} />
      )}

      {isMember && isPlaying && (
        <div className="space-y-3">
          <button
            onClick={onClaimWin}
            disabled={busy}
            data-testid="win-btn"
            className="w-full truncate rounded-xl bg-primary px-4 py-4 text-base font-bold text-on-primary disabled:opacity-50"
          >
            {forGuest ? `Win · ${actorName}` : "Win"}
          </button>
          {state.rules?.special_hands_enabled &&
            (confirmSpecial ? (
              // A special settles instantly and charges everyone else, so a
              // stray tap costs real money — make it deliberate.
              <div className="space-y-2 rounded-xl border border-brand-strong bg-highlight px-3 py-2.5">
                <p className="text-center text-xs text-brand">
                  {forGuest
                    ? `Charge everyone else for ${actorName}'s special hand?`
                    : "Charge everyone else for a special hand?"}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      setConfirmSpecial(false);
                      onSpecialHand();
                    }}
                    disabled={busy}
                    data-testid="confirm-special-btn"
                    className="flex-1 rounded-xl bg-primary py-2.5 text-xs font-semibold text-on-primary disabled:opacity-50"
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
                className="w-full truncate rounded-xl border border-border px-4 py-3 text-sm font-semibold text-brand disabled:opacity-50"
              >
                {forGuest ? `Special Hand · ${actorName}` : "Special Hand"}
              </button>
            ))}

        </div>
      )}

      {isMember && isCollecting && iAmWinner && (
        <p data-testid="waiting-text" className="text-center text-sm text-muted">
          Waiting for {pending.map(nameOf).join(", ")}…
        </p>
      )}

      {isMember && isCollecting && !iAmWinner && !haveSubmitted && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            // 0 is the winner's count — the engine rejects it, so don't
            // let the form send it in the first place.
            if (cardsValid && cardsValue !== null) onSubmitCards(cardsValue);
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
            max={52}
            step={1}
            data-testid="cards-input"
            className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-center text-lg outline-none focus:border-brand-strong"
            value={cardsInput}
            onChange={(e) => setCardsInput(e.target.value)}
            autoFocus
          />
          <button
            type="submit"
            disabled={busy || !cardsValid}
            data-testid="submit-cards-btn"
            className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary disabled:opacity-50"
          >
            Submit
          </button>
        </form>
      )}

      {isMember && isCollecting && !iAmWinner && haveSubmitted && (
        <p data-testid="waiting-text" className="text-center text-sm text-muted">
          Waiting for {pending.map(nameOf).join(", ")}…
        </p>
      )}

      {isMember && guestsOwing.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-widest text-muted">Guest card counts</p>
          {guestsOwing.map((g) => (
            <GuestCardsRow key={g.player_id} guest={g} busy={busy} onSubmit={onSubmitGuestCards} />
          ))}
        </div>
      )}

      <RoundLog rounds={state.rounds} me={me} nameOf={nameOf} />

      {/* Everything below here either reverses something or ends the
          night. Grouped, small and confirm-gated, kept well away from Win
          and Special — the buttons people reach for mid-hand. */}
      {isMember && (actorSpecials > 0 || (isCollecting && (isHost || iAmWinner))) && (
        <div className="space-y-2 rounded-xl border border-border bg-surface px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wider text-muted">Fix a mistake</p>

        {/* Voiding a round deliberately leaves specials alone, so this is
            the only way back from a mistaken claim. */}
        {actorSpecials > 0 && (
          <button
            onClick={onVoidSpecial}
            disabled={busy}
            data-testid="undo-special-btn"
            className="w-full truncate rounded-lg border border-border px-3 py-2 text-xs font-semibold text-muted disabled:opacity-50"
          >
            {forGuest ? `Undo ${actorName}'s special hand` : "Undo my special hand"}
            {actorSpecials > 1 ? ` (${actorSpecials})` : ""}
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
                  className="flex-1 rounded-lg bg-danger-fill py-2 text-xs font-semibold text-on-primary disabled:opacity-50"
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
      {isMember && (
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
                    className="flex-1 rounded-lg bg-danger-fill py-2 text-xs font-semibold text-on-primary disabled:opacity-50"
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
                {forGuest
                  ? `Take ${actorName} out for good? They keep what they're up or down and settle with everyone.`
                  : "Leave for good? You keep what you're up or down and settle with everyone, but you can't rejoin this game."}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setConfirmLeave(false);
                    onStepOut();
                  }}
                  disabled={busy}
                  data-testid="confirm-leave-btn"
                  className="flex-1 rounded-lg bg-danger-fill py-2 text-xs font-semibold text-on-primary disabled:opacity-50"
                >
                  {forGuest ? "Take out" : "Leave game"}
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
              className="mt-2 w-full truncate rounded-lg border border-border px-3 py-2 text-xs font-semibold text-muted disabled:opacity-50"
            >
              {forGuest ? `Take ${actorName} out` : "Leave game"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** One guest's card count, entered by the host. */
function GuestCardsRow({
  guest,
  busy,
  onSubmit,
}: {
  guest: Member;
  busy: boolean;
  onSubmit: (guestId: string, cards: number) => Promise<boolean>;
}) {
  const [value, setValue] = useState("");
  const n = /^\d+$/.test(value.trim()) ? Number(value.trim()) : null;
  const valid = n !== null && n >= 1 && n <= 52;
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (valid && n !== null && (await onSubmit(guest.player_id, n))) setValue("");
      }}
      data-testid="guest-cards-row"
      data-player={guest.display_name}
      className="flex items-center gap-2 rounded-xl border border-border bg-surface py-2 pl-4 pr-2"
    >
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{guest.display_name}</span>
      <input
        type="number"
        inputMode="numeric"
        min={1}
        max={52}
        step={1}
        aria-label={`${guest.display_name}'s cards`}
        data-testid="guest-cards-input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="w-16 shrink-0 rounded-lg border border-border bg-background px-2 py-2 text-center outline-none focus:border-brand-strong"
      />
      <button
        type="submit"
        disabled={busy || !valid}
        data-testid="guest-cards-submit"
        className="shrink-0 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-on-primary disabled:opacity-50"
      >
        Submit
      </button>
    </form>
  );
}

function EndedView({
  standings,
  nameOf,
  profiles,
  roundsPlayed,
  onHome,
}: {
  standings: [string, number][];
  nameOf: (id: string) => string;
  profiles: Record<string, UserProfile>;
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
            className={`flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-sm ${
              idx === 0 ? "border-gold bg-highlight" : "border-border bg-surface"
            }`}
          >
            <PlayerLabel playerId={playerId} name={nameOf(playerId)} profile={profiles[playerId]} link />
            <span
              data-testid="standing-amount"
              className={`shrink-0 font-bold tabular ${cents < 0 ? "text-danger" : "text-brand-strong"}`}
            >
              {money(cents)}
            </span>
          </div>
        ))}
      </div>
      <button
        onClick={onHome}
        data-testid="back-to-home-btn"
        className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary"
      >
        Back to Home
      </button>
    </div>
  );
}
