const selected = new Set();

function updateToolbar() {
  const countEl = document.getElementById("selected-count");
  const deleteBtn = document.getElementById("delete-selected");
  if (!countEl || !deleteBtn) return; // this script is shared across pages that don't all have a toolbar
  countEl.textContent = `${selected.size} selected`;
  deleteBtn.disabled = selected.size === 0;
}

document.getElementById("delete-all-bad")?.addEventListener("click", async () => {
  if (!confirm("Delete ALL clips currently classified as bad (no detect)? They will be moved to the trash directory.")) return;
  await fetch("/clips/delete_all_bad", { method: "POST" });
  window.location.reload();
});

document.querySelectorAll(".select-box").forEach((box) => {
  box.addEventListener("click", (e) => e.stopPropagation());
  box.addEventListener("change", () => {
    const id = Number(box.dataset.clipId);
    if (box.checked) selected.add(id);
    else selected.delete(id);
    updateToolbar();
  });
});

document.getElementById("delete-selected")?.addEventListener("click", async () => {
  if (selected.size === 0) return;
  if (!confirm(`Delete ${selected.size} clip(s)? They will be moved to the trash directory.`)) return;
  await fetch("/clips/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_ids: Array.from(selected) }),
  });
  selected.forEach((id) => {
    const tile = document.querySelector(`.tile[data-clip-id="${id}"]`);
    if (tile) tile.remove();
  });
  selected.clear();
  updateToolbar();
});

document.querySelectorAll(".delete-hour").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const day = btn.dataset.day;
    const hour = btn.dataset.hour;
    // Only delete what the current filter is actually showing - not every
    // status in that hour - so this matches what's on screen.
    const filter = document.body.dataset.filter || "all";
    const scope = filter === "all" ? "" : `${filter} `;
    if (!confirm(`Delete all ${scope}clips for ${day} ${hour}:00? They will be moved to the trash directory.`)) return;
    const body = new URLSearchParams({ day, hour, filter });
    await fetch("/clips/delete_hour", { method: "POST", body });
    btn.closest(".hour-group").remove();
  });
});

document.querySelectorAll(".thumb-wrap").forEach((wrap) => {
  wrap.addEventListener("click", () => {
    const url = wrap.dataset.videoUrl;
    const modal = document.getElementById("modal");
    const video = document.getElementById("modal-video");
    modal.dataset.clipId = wrap.dataset.clipId;
    video.src = url;
    modal.classList.add("open");
    video.play().catch(() => {});
  });
});

function closeModal() {
  const modal = document.getElementById("modal");
  const video = document.getElementById("modal-video");
  video.pause();
  video.src = "";
  modal.classList.remove("open");
}

document.getElementById("modal-close")?.addEventListener("click", closeModal);
document.getElementById("modal")?.addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal();
});

async function sendFeedback(id, label) {
  const body = new URLSearchParams({ label });
  await fetch(`/clips/${id}/feedback`, { method: "POST", body });
  const tile = document.querySelector(`.tile[data-clip-id="${id}"]`);
  if (tile) {
    const badge = tile.querySelector(".badge");
    const newStatus = label === "good" ? "good" : "no_detect";
    badge.className = `badge ${newStatus}`;
    badge.textContent = newStatus.replace("_", " ");
  }
}

document.querySelectorAll(".good-btn, .bad-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    // tile buttons carry their own clip id; the modal's buttons don't (the
    // clip changes each time it's opened), so fall back to the id the modal
    // recorded when the currently-playing video was opened.
    const id = btn.dataset.clipId || document.getElementById("modal")?.dataset.clipId;
    if (!id) return;
    await sendFeedback(id, btn.dataset.label);
  });
});

document.querySelectorAll(".reprocess-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const id = btn.dataset.clipId;
    btn.disabled = true;
    btn.textContent = "Reprocessing…";
    try {
      await fetch(`/clips/${id}/reprocess`, { method: "POST" });
      // status/thumbnail/output folder can all change - simplest correct
      // way to reflect that everywhere (badge, thumbnail, filter, grouping) is to reload.
      window.location.reload();
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Reprocess";
      alert("Reprocessing failed - check the Errors page.");
    }
  });
});

updateToolbar();

function formatElapsed(startedAtIso) {
  if (!startedAtIso) return "";
  const start = new Date(startedAtIso + "Z");
  const secs = Math.max(0, Math.floor((Date.now() - start.getTime()) / 1000));
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

async function refreshStatus() {
  const el = document.getElementById("worker-status");
  if (!el) return;
  try {
    const res = await fetch("/api/status");
    const data = await res.json();

    let text;
    if (data.state === "processing") {
      text = `Processing ${data.current_index} of ${data.total}: ${data.current_event_id} `
        + `(${formatElapsed(data.current_started_at)} elapsed)`;
    } else if (data.state === "scanning") {
      text = "Scanning for new clips&hellip;";
    } else if (data.last_cycle_finished_at) {
      const finished = new Date(data.last_cycle_finished_at + "Z");
      text = `Idle &mdash; last scan finished at ${finished.toLocaleTimeString()}`;
    } else {
      text = "Idle";
    }

    if (data.error_clip_count > 0) {
      text += ` &mdash; <a href="/errors" class="error-link">&#9888; ${data.error_clip_count} clip(s) failed, view errors</a>`;
    }

    el.innerHTML = text;
    el.className = "status-bar"
      + (data.state === "processing" || data.state === "scanning" ? " active" : "")
      + (data.error_clip_count > 0 ? " has-errors" : "");
  } catch (e) {
    el.textContent = "Could not reach the server to check processing status.";
    el.className = "status-bar has-errors";
  }
}

refreshStatus();
setInterval(refreshStatus, 3000);

document.getElementById("shutdown-btn")?.addEventListener("click", async () => {
  if (!confirm("Shut down the server? You'll need to start it again manually (e.g. python -m app.main).")) return;
  await fetch("/admin/shutdown", { method: "POST" });
  document.body.innerHTML = '<main><p class="empty-state">Server is shutting down.</p></main>';
});
