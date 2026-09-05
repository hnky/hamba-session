(() => {
  const input = document.getElementById("image_file");
  const zone = document.getElementById("image-drop-zone");
  const preview = document.getElementById("upload-preview");
  const status = document.getElementById("upload-status");
  const remove = document.getElementById("remove-upload");
  if (!input || !zone || !preview || !status || !remove) return;

  let previewUrl = null;
  function clear(message = "") {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    input.value = "";
    preview.removeAttribute("src");
    preview.hidden = true;
    remove.hidden = true;
    status.textContent = message;
  }

  function showSelected() {
    const file = input.files[0];
    if (!file) {
      clear();
      return;
    }
    if (!/\.(jpe?g|png|webp)$/i.test(file.name) ||
        (file.type && !["image/jpeg", "image/png", "image/webp"].includes(file.type))) {
      clear("Choose a JPEG, PNG, or WebP image.");
      return;
    }
    if (!file.size || file.size > 8 * 1024 * 1024) {
      clear("Choose a non-empty image no larger than 8 MB.");
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    preview.hidden = false;
    remove.hidden = false;
    status.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB · Uploads when you save.`;
  }

  preview.addEventListener("load", () => {
    if (preview.naturalWidth * preview.naturalHeight > 20000000) {
      clear("Choose an image no larger than 20 megapixels.");
    }
  });
  preview.addEventListener("error", () => {
    if (previewUrl) clear("This file could not be read as an image. Choose another image.");
  });
  input.addEventListener("change", showSelected);
  remove.addEventListener("click", () => clear("Selected image removed."));

  for (const event of ["dragenter", "dragover"]) {
    zone.addEventListener(event, (e) => {
      e.preventDefault();
      zone.classList.add("border-coral", "bg-sand");
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    });
  }
  zone.addEventListener("dragleave", (e) => {
    if (!zone.contains(e.relatedTarget)) zone.classList.remove("border-coral", "bg-sand");
  });
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("border-coral", "bg-sand");
    const files = e.dataTransfer?.files;
    if (!files || files.length !== 1) {
      clear("Drop exactly one image at a time.");
      return;
    }
    input.files = files;
    showSelected();
  });
  // Prevent dropped files outside the target from navigating away from edits.
  for (const event of ["dragover", "drop"]) {
    document.addEventListener(event, (e) => {
      if (Array.from(e.dataTransfer?.types || []).includes("Files")) e.preventDefault();
    });
  }
  window.addEventListener("pagehide", () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  });
})();