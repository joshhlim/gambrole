"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { chips } from "@/lib/format";
import { mahjongApi } from "@/lib/mahjongApi";
import { describeMahjongRules } from "@/lib/rulesSummary";
import { SEAT_LABELS, type HandState, type MahjongRoomState } from "@/lib/mahjongTypes";
import type { AnyRoomState, Member } from "@/lib/types";
import { useRoom, type RunOptions } from "./useRoom";
import { ConfirmAction, RoomFrame, RoomLoading, RoomProblem, RulesLine } from "./RoomShell";

function seatLabel(seat: number) {
  return SEAT_LABELS[seat];
}

const narrow = (s: AnyRoomState) => (s.game_type === "mahjong" ? s : null);

/** The hand a command is about: the last one as this device saw it. */
const lastHandNo = (s: MahjongRoomState) => s.hands[s.hands.length - 1]?.hand_no ?? 0;

type Run = (
  action: (s: MahjongRoomState) => Promise<MahjongRoomState>,
  opts?: RunOptions,
) => Promise<MahjongRoomState | null>;

/** seatsFromMe (see TableView) is [you, next, opposite, previous] — this
 * maps that order onto a diamond around the table: you at the bottom,
 * the next seat clockwise on your right, the previous seat on your left. */
const SEAT_POSITIONS = ["bottom", "right", "top", "left"] as const;

export default function MahjongRoom({
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
  const { state, problem, isMember, isHost, busy, banner, blockedBy, run } =
    useRoom<MahjongRoomState>({
      roomId,
      me,
      narrow,
      join: useCallback((id: string) => mahjongApi.join(id), []),
      initial,
      onWrongGame,
      movedOn: "That hand already moved on.",
    });

  const membersBySeat = useMemo(
    () => (state ? Object.values(state.members).sort((a, b) => a.seat - b.seat) : []),
    [state],
  );

  if (problem === "not-found" || problem === "forbidden") return <RoomProblem kind={problem} />;
  if (!state) return <RoomLoading offline={problem === "offline"} />;

  const nameOf = (id: string) => state.members[id]?.display_name ?? "?";
  const rules = state.rules ?? state.draft_rules;

  return (
    <RoomFrame offline={problem === "offline"} banner={banner} blockedBy={blockedBy}>
      {state.status === "lobby" && (
        <Lobby
          state={state}
          isHost={isHost}
          isMember={isMember}
          canJoin={!blockedBy}
          membersBySeat={membersBySeat}
          busy={busy}
          rulesText={rules ? describeMahjongRules(rules) : null}
          onJoin={() => run(() => mahjongApi.join(roomId))}
          onStart={() => run((s) => mahjongApi.start(roomId, s.seq))}
          onLeave={() =>
            run((s) => mahjongApi.leave(roomId, s.seq), { apply: false }).then(
              (r) => r && router.push("/"),
            )
          }
          onDisband={() =>
            run((s) => mahjongApi.disband(roomId, s.seq), { apply: false }).then(
              (r) => r && router.push("/"),
            )
          }
          onSwapSeats={(seatMap) => run((s) => mahjongApi.assignSeats(roomId, s.seq, seatMap))}
        />
      )}

      {state.status === "in_progress" && (
        <TableView
          state={state}
          me={me}
          isHost={isHost}
          isMember={isMember}
          busy={busy}
          run={run}
          roomId={roomId}
        />
      )}

      {state.status === "ended" && (
        <EndedView
          state={state}
          nameOf={nameOf}
          onHome={() => router.push("/")}
        />
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
  busy,
  rulesText,
  onJoin,
  onStart,
  onLeave,
  onDisband,
  onSwapSeats,
}: {
  state: MahjongRoomState;
  isHost: boolean;
  isMember: boolean;
  canJoin: boolean;
  membersBySeat: Member[];
  busy: boolean;
  rulesText: string | null;
  onJoin: () => void;
  onStart: () => void;
  onLeave: () => void;
  onDisband: () => void;
  onSwapSeats: (seatMap: Record<string, number>) => void;
}) {
  const [confirmDisband, setConfirmDisband] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const canRearrange = isHost && membersBySeat.length === 4;

  function tapSeat(playerId: string) {
    if (!canRearrange || busy) return;
    if (picked === null) {
      setPicked(playerId);
      return;
    }
    if (picked === playerId) {
      setPicked(null);
      return;
    }
    const a = state.members[picked];
    const b = state.members[playerId];
    onSwapSeats({ [picked]: b.seat, [playerId]: a.seat });
    setPicked(null);
  }

  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-xs uppercase tracking-widest text-muted mb-1">Room code</p>
        <p data-testid="invite-code" className="text-3xl font-extrabold tracking-[0.3em] text-brand">
          {state.invite_code}
        </p>
      </div>

      <RulesLine text={rulesText} />

      <div>
        <p className="text-xs uppercase tracking-widest text-muted mb-2">
          Players{canRearrange && " — tap two to swap seats"}
        </p>
        <div className="space-y-2">
          {membersBySeat.map((m) => {
            const label = seatLabel(m.seat);
            return (
              <button
                key={m.player_id}
                type="button"
                onClick={() => tapSeat(m.player_id)}
                disabled={!canRearrange || busy}
                data-testid="lobby-member"
                data-seat={m.seat}
                className={`w-full flex items-center gap-3 rounded-xl border px-4 py-3 text-sm font-medium text-left ${
                  picked === m.player_id ? "border-brand-strong bg-[#FFF8E1]" : "border-border bg-surface"
                }`}
              >
                <span className="text-xs font-bold text-brand w-10 shrink-0">
                  {label.han} {label.pinyin}
                </span>
                <span className="flex-1">{m.display_name}</span>
                {m.player_id === state.host_id && (
                  <span className="text-xs font-semibold text-gold-text">HOST</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {!isMember ? (
        // See TaidiRoom: hidden when the one-room rule would refuse it.
        canJoin ? (
          <button
            onClick={onJoin}
            disabled={busy || membersBySeat.length >= 4}
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
            disabled={busy || membersBySeat.length !== 4}
            data-testid="start-game-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            {membersBySeat.length !== 4 ? "Waiting for 4 players…" : "Start Game"}
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
              Disband Room
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

type Action = "yao" | "gang" | "hu";

function TableView({
  state,
  me,
  isHost,
  isMember,
  busy,
  run,
  roomId,
}: {
  state: MahjongRoomState;
  me: string;
  isHost: boolean;
  isMember: boolean;
  busy: boolean;
  run: Run;
  roomId: string;
}) {
  // A flow belongs to the hand it was opened on: its submit is pinned to
  // that hand, and it closes by itself once the table has moved past it —
  // a HU half-entered for hand 3 must never land on hand 4.
  const [opened, setOpened] = useState<{ kind: Action; handNo: number } | null>(null);
  const hand = state.hands[state.hands.length - 1] as HandState | undefined;
  const action = opened && opened.handNo === hand?.hand_no ? opened.kind : null;
  const flowHand = opened?.handNo ?? 0;
  const openFlow = (kind: Action) => hand && setOpened({ kind, handNo: hand.hand_no });
  const mySeat = state.members[me]?.seat ?? 0;
  const seatsFromMe = [0, 1, 2, 3].map((i) => (mySeat + i) % 4);
  const bySeat = useMemo(() => {
    const arr: (Member | undefined)[] = [undefined, undefined, undefined, undefined];
    for (const m of Object.values(state.members)) arr[m.seat] = m;
    return arr;
  }, [state.members]);

  function reset() {
    setOpened(null);
  }

  if (state.pending_wind_decision) {
    return (
      <WindDecisionView
        isHost={isHost}
        busy={busy}
        onContinue={() =>
          run((s) => mahjongApi.continueWind(roomId, s.seq, lastHandNo(s)), { pinned: true })
        }
        onEnd={() => run((s) => mahjongApi.endGame(roomId, s.seq))}
      />
    );
  }

  return (
    <div className="space-y-6">
      {hand && (
        // minmax(0, 1fr), not 1fr: a 1fr track won't shrink below its
        // content, which is what pushed the diamond off a 320px screen.
        // Every card is its column's width (capped), so all four stay the
        // same size whatever the names.
        <div
          className="relative mx-auto grid w-full max-w-[22rem] items-center justify-items-center gap-2"
          style={{
            gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
            gridTemplateAreas: `". top ." "left center right" ". bottom ."`,
          }}
        >
          {seatsFromMe.map((seat, i) => {
            const m = bySeat[seat];
            if (!m) return null;
            const label = seatLabel(seat);
            const net = state.balances[m.player_id] ?? 0;
            const stack = (state.rules?.base_chips ?? 0) + net;
            const isDealer = seat === hand.dealer_seat;
            return (
              <div
                key={m.player_id}
                style={{ gridArea: SEAT_POSITIONS[i] }}
                data-testid="standing-row"
                data-player={m.display_name}
                data-dealer={isDealer}
                className={`flex aspect-square w-full max-w-28 min-w-0 flex-col items-center justify-center gap-0.5 rounded-2xl border px-1.5 text-center text-xs ${
                  isDealer ? "border-gold bg-[#FFF8E1]" : "border-border bg-surface"
                }`}
              >
                <span className="text-xs font-bold text-brand">
                  {label.han} {label.pinyin}
                </span>
                <span className="flex max-w-full items-baseline gap-1">
                  <span className="truncate font-medium">{m.display_name}</span>
                  {m.player_id === me && (
                    <span className="shrink-0 text-muted">(you)</span>
                  )}
                </span>
                <span
                  data-testid="standing-amount"
                  className={`text-sm font-bold ${net < 0 ? "text-danger" : "text-brand-strong"}`}
                >
                  {chips(stack)}
                </span>
              </div>
            );
          })}

          <div
            style={{ gridArea: "center" }}
            data-testid="dealer-seat"
            data-wind={hand.wind}
            data-dealer-seat={hand.dealer_seat}
            data-hand={hand.hand_no}
            className="flex h-14 w-14 items-center justify-center rounded-full border-2 border-gold bg-[#FFF8E1] min-[390px]:h-16 min-[390px]:w-16"
          >
            <span className="text-lg font-extrabold text-brand">
              {seatLabel((hand.wind - 1) % 4).han}
              {seatLabel(hand.dealer_seat).han}
            </span>
          </div>
        </div>
      )}

      {state.rules && <RulesLine text={describeMahjongRules(state.rules)} />}

      {/* Watching without a seat: the table, but nothing to press. */}
      {isMember && action === null && (
        <div className="space-y-3">
          <button
            onClick={() => openFlow("yao")}
            disabled={busy}
            data-testid="yao-btn"
            className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
          >
            咬 YAO
          </button>
          <button
            onClick={() => openFlow("gang")}
            disabled={busy}
            data-testid="gang-btn"
            className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
          >
            槓 GANG
          </button>
          <button
            onClick={() => openFlow("hu")}
            disabled={busy}
            data-testid="hu-btn"
            className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
          >
            胡了 HU LE
          </button>
          {/* Closes the hand and can pass the deal on, with no undo — so
              it asks first, like End. */}
          <ConfirmAction
            label="No Win"
            prompt="Close this hand with no winner?"
            confirmLabel="No win"
            testIds={{ open: "no-win-btn", confirm: "confirm-no-win-btn", cancel: "cancel-no-win-btn" }}
            busy={busy}
            onConfirm={() =>
              run((s) => mahjongApi.declareNoWin(roomId, s.seq, lastHandNo(s)), { pinned: true })
            }
            buttonClassName="w-full rounded-xl border border-border py-3 text-sm font-semibold text-brand disabled:opacity-50"
          />
          {isHost && (
            <ConfirmAction
              label="End Game Now"
              prompt="End the game and settle up? This can't be undone."
              confirmLabel="End & settle"
              testIds={{ open: "end-game-btn", confirm: "confirm-end-btn", cancel: "cancel-end-btn" }}
              busy={busy}
              onConfirm={() => run((s) => mahjongApi.endGame(roomId, s.seq))}
              buttonClassName="w-full rounded-xl border border-border py-2.5 text-xs font-semibold text-muted disabled:opacity-50"
            />
          )}
        </div>
      )}

      {isMember && action === "yao" && (
        <YaoFlow
          me={me}
          bySeat={bySeat}
          busy={busy}
          onCancel={reset}
          onSubmit={(targetSeat, an) =>
            run((s) => mahjongApi.declareYao(roomId, s.seq, flowHand, targetSeat, an), {
              pinned: true,
            }).then((r) => r && reset())
          }
        />
      )}

      {isMember && action === "gang" && (
        <GangFlow
          bySeat={bySeat}
          busy={busy}
          onCancel={reset}
          onSubmit={(target) =>
            run((s) => mahjongApi.declareGang(roomId, s.seq, flowHand, target), {
              pinned: true,
            }).then((r) => r && reset())
          }
        />
      )}

      {isMember && action === "hu" && (
        <HuFlow
          me={me}
          bySeat={bySeat}
          busy={busy}
          maxTai={state.rules?.max_tai ?? 10}
          onCancel={reset}
          onSubmit={(mode, targetSeat, tai, zimoBonus, klppdd) =>
            run(
              (s) =>
                mahjongApi.declareHu(
                  roomId,
                  s.seq,
                  flowHand,
                  mode,
                  targetSeat,
                  tai,
                  zimoBonus,
                  klppdd,
                ),
              { pinned: true },
            ).then((r) => r && reset())
          }
        />
      )}
    </div>
  );
}

/** `busy` matters here: in GangFlow a seat tap *is* the submit, so an
 * enabled seat button during a request is a double charge waiting to
 * happen. */
function PlayerPicker({
  bySeat,
  exclude,
  busy,
  onPick,
}: {
  bySeat: (Member | undefined)[];
  exclude?: number;
  busy: boolean;
  onPick: (seat: number) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {[0, 1, 2, 3].map((seat) => {
        if (seat === exclude) return null;
        const m = bySeat[seat];
        const label = seatLabel(seat);
        return (
          <button
            key={seat}
            type="button"
            onClick={() => onPick(seat)}
            disabled={busy}
            data-testid={`pick-seat-${seat}`}
            className="min-w-0 rounded-xl border border-border bg-surface px-3 py-4 text-sm font-semibold disabled:opacity-50"
          >
            <div className="text-brand">{label.han} {label.pinyin}</div>
            <div className="mt-0.5 truncate text-xs text-muted">{m?.display_name ?? "?"}</div>
          </button>
        );
      })}
    </div>
  );
}

function CancelButton({ onCancel }: { onCancel: () => void }) {
  return (
    <button
      type="button"
      onClick={onCancel}
      data-testid="cancel-action-btn"
      className="w-full text-center text-xs text-muted"
    >
      Cancel
    </button>
  );
}

function YaoFlow({
  me,
  bySeat,
  busy,
  onCancel,
  onSubmit,
}: {
  me: string;
  bySeat: (Member | undefined)[];
  busy: boolean;
  onCancel: () => void;
  onSubmit: (targetSeat: number, an: boolean) => void;
}) {
  const [targetSeat, setTargetSeat] = useState<number | null>(null);

  if (targetSeat === null) {
    return (
      <div className="space-y-3">
        <p className="text-center text-sm text-muted">咬 Who are you biting?</p>
        <PlayerPicker bySeat={bySeat} busy={busy} onPick={setTargetSeat} />
        <CancelButton onCancel={onCancel} />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-center text-sm text-muted">
        {bySeat[targetSeat]?.player_id === me ? "咬自己 Biting yourself" : `Biting ${bySeat[targetSeat]?.display_name}`}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={() => onSubmit(targetSeat, false)}
          disabled={busy}
          data-testid="yao-ming-btn"
          className="rounded-xl bg-brand py-4 text-sm font-bold text-white disabled:opacity-50"
        >
          咬 YAO
        </button>
        <button
          onClick={() => onSubmit(targetSeat, true)}
          disabled={busy}
          data-testid="yao-an-btn"
          className="rounded-xl bg-brand-strong py-4 text-sm font-bold text-white disabled:opacity-50"
        >
          暗咬 ANYAO
        </button>
      </div>
      <CancelButton onCancel={onCancel} />
    </div>
  );
}

function GangFlow({
  bySeat,
  busy,
  onCancel,
  onSubmit,
}: {
  bySeat: (Member | undefined)[];
  busy: boolean;
  onCancel: () => void;
  onSubmit: (target: number | "angang") => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-center text-sm text-muted">槓 Who gangs?</p>
      <PlayerPicker bySeat={bySeat} busy={busy} onPick={onSubmit} />
      <button
        onClick={() => onSubmit("angang")}
        disabled={busy}
        data-testid="pick-angang"
        className="w-full rounded-xl border border-brand-strong bg-surface px-3 py-3 text-sm font-semibold text-brand disabled:opacity-50"
      >
        暗槓 ANGANG
      </button>
      <CancelButton onCancel={onCancel} />
    </div>
  );
}

function HuFlow({
  me,
  bySeat,
  busy,
  maxTai,
  onCancel,
  onSubmit,
}: {
  me: string;
  bySeat: (Member | undefined)[];
  busy: boolean;
  maxTai: number;
  onCancel: () => void;
  onSubmit: (
    mode: "direct" | "zimo" | "bao",
    targetSeat: number | null,
    tai: number,
    zimoBonus: boolean,
    klppdd: boolean,
  ) => void;
}) {
  const [step, setStep] = useState<"pick" | "pick-bao" | "tai">("pick");
  const [mode, setMode] = useState<"direct" | "zimo" | "bao">("direct");
  const [targetSeat, setTargetSeat] = useState<number | null>(null);
  const [tai, setTai] = useState(1);
  const [zimoBonus, setZimoBonus] = useState(false);
  const [klppdd, setKlppdd] = useState(false);
  const mySeat = Object.values(bySeat).find((m) => m?.player_id === me)?.seat;

  if (step === "pick") {
    return (
      <div className="space-y-3">
        <p className="text-center text-sm text-muted">胡了 Who did you win off?</p>
        <button
          type="button"
          onClick={() => setStep("pick-bao")}
          data-testid="pick-bao"
          className="w-full rounded-xl border border-brand-strong bg-surface px-3 py-3 text-sm font-semibold text-brand"
        >
          包 BAO (someone covers a self-draw)
        </button>
        <PlayerPicker
          bySeat={bySeat}
          busy={busy}
          onPick={(seat) => {
            const isSelf = bySeat[seat]?.player_id === me;
            setMode(isSelf ? "zimo" : "direct");
            setTargetSeat(isSelf ? null : seat);
            setStep("tai");
          }}
        />
        <CancelButton onCancel={onCancel} />
      </div>
    );
  }

  if (step === "pick-bao") {
    return (
      <div className="space-y-3">
        <p className="text-center text-sm text-muted">包 Who covers?</p>
        <PlayerPicker
          bySeat={bySeat}
          exclude={mySeat}
          busy={busy}
          onPick={(seat) => {
            setMode("bao");
            setTargetSeat(seat);
            setStep("tai");
          }}
        />
        <CancelButton onCancel={onCancel} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-center text-sm text-muted">
        {mode === "zimo" && "自摸 Self-draw"}
        {mode === "direct" && `Off ${bySeat[targetSeat ?? -1]?.display_name}`}
        {mode === "bao" && `包 Covered by ${bySeat[targetSeat ?? -1]?.display_name}`}
      </p>
      <div className="flex items-center justify-center gap-4">
        <button
          type="button"
          onClick={() => setTai((t) => Math.max(1, t - 1))}
          data-testid="tai-minus"
          className="h-12 w-12 rounded-full border border-border text-lg font-bold text-brand"
        >
          −
        </button>
        <div className="text-center">
          <p data-testid="tai-value" className="text-2xl font-extrabold text-brand">{tai}</p>
          <p className="text-xs text-muted">台 TAI</p>
        </div>
        <button
          type="button"
          onClick={() => setTai((t) => Math.min(maxTai, t + 1))}
          data-testid="tai-plus"
          className="h-12 w-12 rounded-full border border-border text-lg font-bold text-brand"
        >
          +
        </button>
      </div>
      <div className="space-y-2">
        {mode === "zimo" && (
          <button
            type="button"
            onClick={() => setZimoBonus((v) => !v)}
            data-testid="zimo-bonus-toggle"
            aria-pressed={zimoBonus}
            className={`w-full rounded-xl border px-3 py-2.5 text-sm font-semibold ${
              zimoBonus ? "border-brand-strong bg-[#FFF8E1] text-brand" : "border-border bg-surface text-muted"
            }`}
          >
            Zimo bonus{zimoBonus ? " ✓" : ""}
          </button>
        )}
        <button
          type="button"
          onClick={() => setKlppdd((v) => !v)}
          data-testid="klppdd-toggle"
          aria-pressed={klppdd}
          className={`w-full rounded-xl border px-3 py-2.5 text-sm font-semibold ${
            klppdd ? "border-brand-strong bg-[#FFF8E1] text-brand" : "border-border bg-surface text-muted"
          }`}
        >
          KLPPDD{klppdd ? " ✓" : ""}
        </button>
      </div>
      <button
        onClick={() => onSubmit(mode, targetSeat, tai, zimoBonus, klppdd)}
        disabled={busy}
        data-testid="confirm-hu-btn"
        className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
      >
        胡了 Confirm
      </button>
      <CancelButton onCancel={onCancel} />
    </div>
  );
}

function WindDecisionView({
  isHost,
  busy,
  onContinue,
  onEnd,
}: {
  isHost: boolean;
  busy: boolean;
  onContinue: () => void;
  onEnd: () => void;
}) {
  return (
    <div className="space-y-4 text-center py-8">
      <p data-testid="wind-decision" className="text-lg font-extrabold text-brand">
        4 winds complete
      </p>
      {isHost ? (
        <div className="space-y-3">
          <button
            onClick={onContinue}
            disabled={busy}
            data-testid="continue-wind-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Continue
          </button>
          <ConfirmAction
            label="End Game"
            prompt="End the game and settle up? This can't be undone."
            confirmLabel="End & settle"
            testIds={{ open: "end-game-btn", confirm: "confirm-end-btn", cancel: "cancel-end-btn" }}
            busy={busy}
            onConfirm={onEnd}
            buttonClassName="w-full rounded-xl border border-border py-3 text-sm font-semibold text-muted disabled:opacity-50"
          />
        </div>
      ) : (
        <p className="text-sm text-muted">Waiting for the host to continue or end the game…</p>
      )}
    </div>
  );
}

function EndedView({
  state,
  nameOf,
  onHome,
}: {
  state: MahjongRoomState;
  nameOf: (id: string) => string;
  onHome: () => void;
}) {
  const baseChips = state.rules?.base_chips ?? 0;
  const standings = Object.entries(state.balances).sort(([, a], [, b]) => b - a);
  const [topId, topNet] = standings[0] ?? [null, 0];

  return (
    <div className="space-y-6">
      <div className="text-center space-y-1">
        <p data-testid="game-over" className="text-lg font-extrabold text-brand">
          Game Over
        </p>
        <p className="text-xs uppercase tracking-widest text-muted">
          {state.hands.length} hand{state.hands.length === 1 ? "" : "s"} played
        </p>
      </div>

      {topId && (
        <p className="text-center text-sm text-muted">
          <span className="font-semibold text-foreground">{nameOf(topId)}</span> wins with{" "}
          <span className="font-bold text-brand-strong">{chips(baseChips + topNet)}</span> chips
        </p>
      )}

      <div className="space-y-2">
        {standings.map(([playerId, net], idx) => (
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
              className={`font-bold ${net < 0 ? "text-danger" : "text-brand-strong"}`}
            >
              {chips(baseChips + net)}
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
