document.querySelectorAll("time[data-local-date]").forEach((element) => {
  const timestamp = new Date(element.dateTime);
  if (Number.isNaN(timestamp.getTime())) return;

  const year = timestamp.getFullYear();
  const month = String(timestamp.getMonth() + 1).padStart(2, "0");
  const day = String(timestamp.getDate()).padStart(2, "0");
  element.textContent = `${year}-${month}-${day}`;
});

document.querySelectorAll("[data-photo-gallery]").forEach((gallery) => {
  const image = gallery.querySelector("[data-gallery-image]");
  const thumbnails = Array.from(
    gallery.querySelectorAll("[data-gallery-thumbnail]"),
  );

  if (!image || thumbnails.length === 0) return;

  const selectPhoto = (selected) => {
    image.src = selected.dataset.gallerySrc;
    image.alt = selected.dataset.galleryAlt;

    thumbnails.forEach((thumbnail) => {
      const isSelected = thumbnail === selected;
      thumbnail.classList.toggle("is-selected", isSelected);
      thumbnail.setAttribute("aria-current", String(isSelected));
    });
  };

  thumbnails.forEach((thumbnail) => {
    thumbnail.addEventListener("click", () => selectPhoto(thumbnail));
  });
});
