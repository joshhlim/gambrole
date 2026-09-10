"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { mahjongApi } from "@/lib/mahjongApi";
import { usePolling } from "@/lib/usePolling";
import { readFreshState } from "@/lib/freshState";
import { SEAT_LABELS, type HandState, type MahjongRoomState, type MahjongRules } from "@/lib/mahjongTypes";
import type { Member } from "@/lib/types";

/** Rules chosen on /new before the room existed — see TaidiRoom's identical
 * readStoredRules for why this can't just be sent at room-creation time. */
function readStoredRules(roomId: string): Partial<MahjongRules> | undefined {
  try {
    const raw = sessionStorage.getItem(`gambrole_rules_${roomId}`);
    return raw ? (JSON.parse(raw) as MahjongRules) : undefined;
  } catch {
    return undefined;
  }
}

function chips(amount: number): string {
  return amount.toLocaleString();
}

function seatLabel(seat: number) {
  return SEAT_LABELS[seat];
}

/** seatsFromMe (see TableView) is [you, next, opposite, previous] — this
 * maps that order onto a diamond around the table: you at the bottom,
 * the next seat clockwise on your right, the previous seat on your left. */
const SEAT_POSITIONS = ["bottom", "right", "top", "left"] as const;

export default function MahjongRoom({ roomId, me }: { roomId: string; me: string }) {
  const router = useRouter();
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const [blockedBy, setBlockedBy] = useState<string | null>(null);
  const joinedRef = useRef(false);

  const { data: state, setData } = usePolling<MahjongRoomState>(
    () => mahjongApi.getState(roomId),
    1500,
    [roomId, me],
    readFreshState<MahjongRoomState>(roomId),
  );

  const isMember = !!(state && me in state.members);

  useEffect(() => {
    if (state?.status === "disbanded") router.replace("/");
  }, [state?.status, router]);

  useEffect(() => {
    if (!state || joinedRef.current) return;
    if (!isMember && state.status === "lobby") {
      joinedRef.current = true;
      mahjongApi
        .join(roomId)
        .then(setData)
        .catch((e) => {
          setBanner(e instanceof ApiError ? e.message : "Couldn't join this room.");
          // See TaidiRoom: refused because you're already in another room.
          const other = (e instanceof ApiError ? e.detail : null) as {
            active_room_id?: string;
          } | null;
          if (other?.active_room_id) setBlockedBy(other.active_room_id);
        });
    }
  }, [state, isMember, roomId, setData]);

  /** See TaidiRoom's identical `run` for the retry-on-409 rationale. */
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
        // ApiError.conflict is typed against Taidi's RoomState — read the
        // detail directly instead, since a Mahjong endpoint's 409 actually
        // carries a MahjongRoomState.
        if (e instanceof ApiError && e.status === 409) {
          const conflict = e.detail as { state: MahjongRoomState };
          setData(conflict.state);
          seq = conflict.state.seq;
          continue;
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

  if (!state) {
    return <main className="flex-1 flex items-center justify-center text-muted text-sm">Loading…</main>;
  }

  const isHost = state.host_id === me;
  const nameOf = (id: string) => state.members[id]?.display_name ?? "?";

  /** See TaidiRoom's handleBack — identical semantics, mahjongApi instead. */
  async function handleBack() {
    if (state && state.status === "lobby" && isMember) {
      if (isHost) {
        if (membersBySeat.length > 1 && !confirmClose) {
          setConfirmClose(true);
          return;
        }
        if (!(await run((seq) => mahjongApi.disband(roomId, seq)))) return;
      } else if (!(await run((seq) => mahjongApi.leave(roomId, seq)))) {
        return;
      }
    }
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
        {confirmClose && (
          <>
            <span className="text-xs text-muted">Close the room for everyone?</span>
            <button
              onClick={handleBack}
              disabled={busy}
              data-testid="confirm-close-btn"
              className="rounded-lg bg-danger px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              Close
            </button>
            <button
              onClick={() => setConfirmClose(false)}
              data-testid="cancel-close-btn"
              className="rounded-lg border border-border px-3 py-2 text-xs font-semibold text-muted"
            >
              Cancel
            </button>
          </>
        )}
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
          onJoin={() => run((_seq) => mahjongApi.join(roomId)).then((r) => r && setData(r))}
          onStart={() =>
            run((seq) => mahjongApi.start(roomId, seq, readStoredRules(roomId))).then(
              (r) => r && setData(r),
            )
          }
          onLeave={() => run((seq) => mahjongApi.leave(roomId, seq)).then((r) => r && router.push("/"))}
          onDisband={() =>
            run((seq) => mahjongApi.disband(roomId, seq)).then((r) => r && router.push("/"))
          }
          onSwapSeats={(seatMap) =>
            run((seq) => mahjongApi.assignSeats(roomId, seq, seatMap)).then((r) => r && setData(r))
          }
        />
      )}

      {state.status === "in_progress" && (
        <TableView
          state={state}
          me={me}
          isHost={isHost}
          busy={busy}
          run={run}
          roomId={roomId}
          setData={setData}
        />
      )}

      {state.status === "ended" && (
        <EndedView
          state={state}
          nameOf={nameOf}
          onHome={() => router.push("/")}
        />
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
  onSwapSeats,
}: {
  state: MahjongRoomState;
  isHost: boolean;
  isMember: boolean;
  canJoin: boolean;
  membersBySeat: Member[];
  busy: boolean;
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
                disabled={!canRearrange}
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
                {m.player_id === state.host_id && <span className="text-xs text-gold">HOST</span>}
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

type Action = "yao" | "gang" | "hu" | null;

function TableView({
  state,
  me,
  isHost,
  busy,
  run,
  roomId,
  setData,
}: {
  state: MahjongRoomState;
  me: string;
  isHost: boolean;
  busy: boolean;
  run: <T>(action: (seq: number) => Promise<T>) => Promise<T | null>;
  roomId: string;
  setData: (s: MahjongRoomState) => void;
}) {
  const [action, setAction] = useState<Action>(null);
  const hand = state.hands[state.hands.length - 1] as HandState | undefined;
  const mySeat = state.members[me]?.seat ?? 0;
  const seatsFromMe = [0, 1, 2, 3].map((i) => (mySeat + i) % 4);
  const bySeat = useMemo(() => {
    const arr: (Member | undefined)[] = [undefined, undefined, undefined, undefined];
    for (const m of Object.values(state.members)) arr[m.seat] = m;
    return arr;
  }, [state.members]);

  function reset() {
    setAction(null);
  }

  if (state.pending_wind_decision) {
    return (
      <WindDecisionView
        isHost={isHost}
        busy={busy}
        onContinue={() =>
          run((seq) => mahjongApi.continueWind(roomId, seq)).then((r) => r && setData(r))
        }
        onEnd={() => run((seq) => mahjongApi.endGame(roomId, seq)).then((r) => r && setData(r))}
      />
    );
  }

  return (
    <div className="space-y-6">
      {hand && (
        <div
          className="relative mx-auto grid w-full max-w-[22rem] items-center justify-items-center gap-2"
          style={{
            gridTemplateColumns: "1fr 1fr 1fr",
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
                className={`flex h-28 w-28 flex-col items-center justify-center gap-0.5 rounded-2xl border px-2 text-center text-xs ${
                  isDealer ? "border-gold bg-[#FFF8E1]" : "border-border bg-surface"
                }`}
              >
                <span className="text-xs font-bold text-brand">
                  {label.han} {label.pinyin}
                </span>
                <span className="flex max-w-[6rem] items-baseline gap-1">
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
            className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-gold bg-[#FFF8E1]"
          >
            <span className="text-lg font-extrabold text-brand">
              {seatLabel((hand.wind - 1) % 4).han}
              {seatLabel(hand.dealer_seat).han}
            </span>
          </div>
        </div>
      )}

      {action === null && (
        <div className="space-y-3">
          <button
            onClick={() => setAction("yao")}
            disabled={busy}
            data-testid="yao-btn"
            className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
          >
            咬 YAO
          </button>
          <button
            onClick={() => setAction("gang")}
            disabled={busy}
            data-testid="gang-btn"
            className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
          >
            槓 GANG
          </button>
          <button
            onClick={() => setAction("hu")}
            disabled={busy}
            data-testid="hu-btn"
            className="w-full rounded-xl bg-brand py-4 text-base font-bold text-white disabled:opacity-50"
          >
            胡了 HU LE
          </button>
          <button
            onClick={() => run((seq) => mahjongApi.declareNoWin(roomId, seq)).then((r) => r && setData(r))}
            disabled={busy}
            data-testid="no-win-btn"
            className="w-full rounded-xl border border-border py-3 text-sm font-semibold text-brand disabled:opacity-50"
          >
            No Win
          </button>
          {isHost && (
            <button
              onClick={() => run((seq) => mahjongApi.endGame(roomId, seq)).then((r) => r && setData(r))}
              disabled={busy}
              data-testid="end-game-btn"
              className="w-full rounded-xl border border-border py-2.5 text-xs font-semibold text-muted disabled:opacity-50"
            >
              End Game Now
            </button>
          )}
        </div>
      )}

      {action === "yao" && (
        <YaoFlow
          me={me}
          bySeat={bySeat}
          busy={busy}
          onCancel={reset}
          onSubmit={(targetSeat, an) =>
            run((seq) => mahjongApi.declareYao(roomId, seq, targetSeat, an)).then((r) => {
              if (r) {
                setData(r);
                reset();
              }
            })
          }
        />
      )}

      {action === "gang" && (
        <GangFlow
          bySeat={bySeat}
          busy={busy}
          onCancel={reset}
          onSubmit={(target) =>
            run((seq) => mahjongApi.declareGang(roomId, seq, target)).then((r) => {
              if (r) {
                setData(r);
                reset();
              }
            })
          }
        />
      )}

      {action === "hu" && (
        <HuFlow
          me={me}
          bySeat={bySeat}
          busy={busy}
          maxTai={state.rules?.max_tai ?? 10}
          onCancel={reset}
          onSubmit={(mode, targetSeat, tai, zimoBonus, klppdd) =>
            run((seq) =>
              mahjongApi.declareHu(roomId, seq, mode, targetSeat, tai, zimoBonus, klppdd),
            ).then((r) => {
              if (r) {
                setData(r);
                reset();
              }
            })
          }
        />
      )}
    </div>
  );
}

function PlayerPicker({
  bySeat,
  exclude,
  onPick,
}: {
  bySeat: (Member | undefined)[];
  exclude?: number;
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
            data-testid={`pick-seat-${seat}`}
            className="rounded-xl border border-border bg-surface px-3 py-4 text-sm font-semibold"
          >
            <div className="text-brand">{label.han} {label.pinyin}</div>
            <div className="text-xs text-muted mt-0.5">{m?.display_name ?? "?"}</div>
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
        <PlayerPicker bySeat={bySeat} onPick={setTargetSeat} />
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
      <PlayerPicker bySeat={bySeat} onPick={onSubmit} />
      <button
        onClick={() => onSubmit("angang")}
        disabled={busy}
        data-testid="pick-angang"
        className="w-full rounded-xl border border-brand-strong bg-surface px-3 py-3 text-sm font-semibold text-brand"
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
          className="h-11 w-11 rounded-full border border-border text-lg font-bold text-brand"
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
          className="h-11 w-11 rounded-full border border-border text-lg font-bold text-brand"
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
          <button
            onClick={onEnd}
            disabled={busy}
            data-testid="end-game-btn"
            className="w-full rounded-xl border border-border py-3 text-sm font-semibold text-muted disabled:opacity-50"
          >
            End Game
          </button>
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
