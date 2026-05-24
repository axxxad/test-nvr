/**
 * Drag-and-drop reorder for the camera grid; persists order via POST /cameras/reorder.
 */
(function () {
  const grid = document.getElementById("camera-grid");
  if (!grid) return;

  const statusEl = document.getElementById("camera-grid-status");
  const reorderUrl = grid.dataset.reorderUrl || "/cameras/reorder";
  let dragged = null;

  function cards() {
    return Array.from(grid.querySelectorAll(".camera-grid-card"));
  }

  function currentOrder() {
    return cards().map((card) => parseInt(card.dataset.cameraId, 10));
  }

  function setStatus(message, isError) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.toggle("text-error", Boolean(isError));
    statusEl.classList.toggle("text-base-content/50", !isError);
  }

  async function saveOrder() {
    setStatus("Saving order…", false);
    try {
      const response = await fetch(reorderUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order: currentOrder() }),
      });
      if (!response.ok) {
        throw new Error("Request failed");
      }
      const data = await response.json();
      if (!data.ok) {
        throw new Error(data.error || "Could not save order");
      }
      setStatus("Order saved.", false);
      window.setTimeout(() => {
        if (statusEl && statusEl.textContent === "Order saved.") {
          statusEl.textContent = "";
        }
      }, 2000);
    } catch {
      setStatus("Could not save order. Refresh and try again.", true);
    }
  }

  function clearDropTargets() {
    cards().forEach((card) => card.classList.remove("camera-grid-drop-target"));
  }

  cards().forEach((card) => {
    const handle = card.querySelector(".camera-grid-drag-handle");
    if (!handle) return;

    handle.addEventListener("dragstart", (event) => {
      dragged = card;
      card.classList.add("camera-grid-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.cameraId || "");
    });

    handle.addEventListener("dragend", () => {
      card.classList.remove("camera-grid-dragging");
      clearDropTargets();
      dragged = null;
    });

    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (!dragged || dragged === card) return;
      event.dataTransfer.dropEffect = "move";
      clearDropTargets();
      card.classList.add("camera-grid-drop-target");
    });

    card.addEventListener("dragleave", (event) => {
      if (event.currentTarget.contains(event.relatedTarget)) return;
      card.classList.remove("camera-grid-drop-target");
    });

    card.addEventListener("drop", (event) => {
      event.preventDefault();
      if (!dragged || dragged === card) return;

      const items = cards();
      const fromIndex = items.indexOf(dragged);
      const toIndex = items.indexOf(card);
      if (fromIndex < 0 || toIndex < 0) return;

      if (fromIndex < toIndex) {
        grid.insertBefore(dragged, card.nextElementSibling);
      } else {
        grid.insertBefore(dragged, card);
      }

      clearDropTargets();
      saveOrder();
    });
  });

  grid.addEventListener("dragover", (event) => {
    event.preventDefault();
  });
})();
