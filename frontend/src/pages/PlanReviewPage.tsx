// Review mode: your generated plan before it goes on the calendar. Each exercise can be kept or swapped for one of
// the options the server offers, which pass the same injury, equipment, level and Push/Pull checks as the plan.
import { useEffect, useState } from "react";
import {
  fetchPlanReview,
  finalizePlanReview,
  isSignInGone,
  MUSCLE_GROUP_LABELS,
  type PlanReview,
} from "../api";
import Link from "../components/Link";
import { navigate } from "../router";
import { setSession, useSession } from "../session";

const DAY_NAMES: Record<string, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

export default function PlanReviewPage() {
  const session = useSession();
  const [review, setReview] = useState<PlanReview | null>(null);
  const [swaps, setSwaps] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!session) return;
    fetchPlanReview(session.token)
      .then((r) => {
        setReview(r);
        setSwaps(r.swaps);
      })
      .catch((e: Error) => {
        if (isSignInGone(e)) setSession(null);
        setError(e.message);
      });
  }, [session]);

  if (!session) return <p>Sign in to review your plan.</p>;
  if (error) return <p className="error">{error}</p>;
  if (!review) return <p className="hint">Loading your plan…</p>;

  const plan = review.plan;
  const options = plan.swap_options ?? {};
  // The plan shown has the saved swaps applied; key each row by the ORIGINAL exercise so swaps line up.
  const original = (id: string, from?: string | null) => from ?? id;

  async function finalize() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const clean = Object.fromEntries(
        Object.entries(swaps).filter(([a, b]) => a !== b),
      );
      await finalizePlanReview(session.token, clean);
      navigate("/calendar");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="plan-review">
      <h2 className="page-title">Review your plan</h2>
      <p className="page-sub">
        Swap anything you don’t love. Every option passed the same safety checks
        as your plan (your injuries, your equipment, your level). When you’re
        happy, put it on your calendar.
      </p>
      {review.calendar_mode !== "review" && (
        <p className="notice">
          Your calendar is set to “{review.calendar_mode}”. Choose “Let me
          review it first” in <Link to="/settings">Settings</Link> to use this
          page.
        </p>
      )}
      <p className="hint">
        Your plan repeats every {plan.block_weeks}{" "}
        {plan.block_weeks === 1 ? "week" : "weeks"}. A swap applies everywhere
        that exercise appears.
      </p>
      {plan.weeks.flatMap((w) =>
        w.days
          .filter((d) => d.kind === "training")
          .map((d) => (
            <section
              key={`${w.week_in_block}-${d.day}`}
              className="dash-card review-day"
            >
              <h3>
                {plan.block_weeks > 1 && <>Week {w.week_in_block}, </>}
                {DAY_NAMES[d.day]} <span className="hint">· {d.focus}</span>
              </h3>
              <ul className="review-list">
                {d.exercises.map((x) => {
                  const key = original(x.exercise_id, x.swapped_from);
                  const opts = options[key] ?? [];
                  return (
                    <li key={`${d.day}-${key}`}>
                      <span className="chip chip-small">
                        {MUSCLE_GROUP_LABELS[x.muscle_group]}
                      </span>
                      <label>
                        <span className="sr-only">
                          Exercise for {DAY_NAMES[d.day]}
                        </span>
                        <select
                          value={swaps[key] ?? key}
                          onChange={(e) =>
                            setSwaps((s) => ({ ...s, [key]: e.target.value }))
                          }
                        >
                          <option value={key}>
                            {key === x.exercise_id
                              ? x.name
                              : `Keep the original`}
                          </option>
                          {x.swapped_from && (
                            <option value={x.exercise_id}>{x.name}</option>
                          )}
                          {opts
                            .filter((o) => o.id !== x.exercise_id)
                            .map((o) => (
                              <option key={o.id} value={o.id}>
                                {o.name}
                                {o.injury_check === "not_yet_checked"
                                  ? " (not yet checked for injuries)"
                                  : ""}
                              </option>
                            ))}
                        </select>
                      </label>
                      <span className="hint">
                        {x.sets} sets ×{" "}
                        {x.reps_your_call ? "your call" : x.reps}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          )),
      )}
      <div className="button-row">
        <button
          type="button"
          className="btn btn-big"
          disabled={busy || review.calendar_mode !== "review"}
          onClick={finalize}
        >
          {busy ? "Saving…" : "Looks good: put it on my calendar"}
        </button>
      </div>
    </div>
  );
}
