let setCounters = {};

async function startSession(dayType, scheduleDayId) {
  const res = await fetch("/api/train/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({day_type: dayType, schedule_day_id: scheduleDayId}),
  });
  const data = await res.json();
  document.getElementById("session-status").textContent = `Session #${data.session_id} in progress`;
  document.getElementById("start-btn").disabled = true;
  document.getElementById("complete-btn").disabled = false;
}

async function completeSession() {
  await fetch("/api/train/complete", {method: "POST"});
  document.getElementById("session-status").textContent = "Session completed. Nice work.";
  document.getElementById("start-btn").disabled = false;
  document.getElementById("complete-btn").disabled = true;
}

async function logSet(card) {
  const exerciseId = card.dataset.exerciseId;
  const metric = card.dataset.metric;
  const input = card.querySelector(".log-value");
  const feedbackEl = card.querySelector(".feedback");
  const value = parseFloat(input.value);
  if (isNaN(value)) return;

  const setNo = (setCounters[exerciseId] || 0) + 1;
  setCounters[exerciseId] = setNo;

  const payload = {
    exercise_id: exerciseId,
    set_number: setNo,
    target_low: parseFloat(card.dataset.targetLow),
    target_high: parseFloat(card.dataset.targetHigh),
  };
  if (metric === "hold_seconds") payload.hold_done = value;
  else payload.reps_done = Math.round(value);

  const res = await fetch("/api/train/log_set", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const fb = await res.json();
  feedbackEl.textContent = fb.error ? fb.error : `Set ${setNo}: ${fb.message}`;
  input.value = "";
}

function wireTimer(card) {
  const startBtn = card.querySelector(".timer-start");
  const box = card.querySelector(".timer-box");
  const display = box.querySelector(".timer-display");
  const phaseLabel = box.querySelector(".timer-phase");
  const setCount = box.querySelector(".timer-set-count");
  const pauseBtn = box.querySelector(".timer-pause");
  const skipBtn = box.querySelector(".timer-skip");

  const work = parseInt(card.dataset.work, 10);
  const rest = parseInt(card.dataset.rest, 10);
  const sets = parseInt(card.dataset.sets, 10);

  let timer = null;

  startBtn.addEventListener("click", () => {
    startBtn.style.display = "none";
    box.style.display = "block";
    timer = new GuidedTimer(work, rest, sets, {
      onTick: (remaining) => { display.textContent = remaining; },
      onPhaseChange: (phase, currentSet, remaining) => {
        display.textContent = remaining;
        phaseLabel.textContent = phase;
        phaseLabel.className = "timer-phase " + phase;
        setCount.textContent = `Set ${currentSet} / ${sets}`;
      },
      onComplete: () => {
        phaseLabel.textContent = "Done!";
        display.textContent = "✓";
      },
      onPauseToggle: (paused) => { pauseBtn.textContent = paused ? "Resume" : "Pause"; },
    });
    timer.start();
  });
  pauseBtn.addEventListener("click", () => timer && timer.pause());
  skipBtn.addEventListener("click", () => timer && timer.skip());
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".card[data-exercise-id]").forEach((card) => {
    wireTimer(card);
    card.querySelector(".log-btn").addEventListener("click", () => logSet(card));
  });
});
