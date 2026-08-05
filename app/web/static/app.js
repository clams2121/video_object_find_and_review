const selected = new Set();

function updateToolbar() {
  document.getElementById("selected-count").textContent = `${selected.size} selected`;
  document.getElementById("delete-selected").disabled = selected.size === 0;
}

document.querySelectorAll(".select-box").forEach((box) => {
  box.addEventListener("click", (e) => e.stopPropagation());
  box.addEventListener("change", () => {
    const id = Number(box.dataset.clipId);
    if (box.checked) selected.add(id);
    else selected.delete(id);
    updateToolbar();
  });
});

document.getElementById("delete-selected").addEventListener("click", async () => {
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
    if (!confirm(`Delete all clips for ${day} ${hour}:00? They will be moved to the trash directory.`)) return;
    const body = new URLSearchParams({ day, hour });
    await fetch("/clips/delete_hour", { method: "POST", body });
    btn.closest(".hour-group").remove();
  });
});

document.querySelectorAll(".thumb-wrap").forEach((wrap) => {
  wrap.addEventListener("click", () => {
    const url = wrap.dataset.videoUrl;
    const modal = document.getElementById("modal");
    const video = document.getElementById("modal-video");
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

document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal();
});

document.querySelectorAll(".good-btn, .bad-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const id = btn.dataset.clipId;
    const label = btn.dataset.label;
    const body = new URLSearchParams({ label });
    await fetch(`/clips/${id}/feedback`, { method: "POST", body });
    const tile = document.querySelector(`.tile[data-clip-id="${id}"]`);
    const badge = tile.querySelector(".badge");
    const newStatus = label === "good" ? "good" : "no_detect";
    badge.className = `badge ${newStatus}`;
    badge.textContent = newStatus.replace("_", " ");
  });
});

updateToolbar();
