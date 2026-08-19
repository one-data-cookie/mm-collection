document.querySelectorAll("time[data-local-date]").forEach((element) => {
  const timestamp = new Date(element.dateTime);
  if (Number.isNaN(timestamp.getTime())) return;

  const year = timestamp.getFullYear();
  const month = String(timestamp.getMonth() + 1).padStart(2, "0");
  const day = String(timestamp.getDate()).padStart(2, "0");
  element.textContent = `${year}-${month}-${day}`;
});
