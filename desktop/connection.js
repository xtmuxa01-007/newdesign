const retry = document.querySelector("#retry");
const error = document.querySelector("#error");
const status = document.querySelector("#status");
const retire = document.querySelector("#retire");
let busy = false;
window.tinConnection.info().then((info) => {
  document.querySelector("#server").textContent = info?.server || "";
  error.textContent = info?.error || "Serverga ulanib bo‘lmadi.";
  document.querySelector("#recovery").hidden = !info?.canRetire;
});
retire.addEventListener("click", async () => {
  busy = true;
  retry.disabled = retire.disabled = true;
  status.textContent = "Eski bazalar zaxiralanmoqda va tekshirilmoqda…";
  try {
    const result = await window.tinConnection.retire();
    if (!result.ok) error.textContent = result.error;
  } catch {
    error.textContent = "Tiklash tugamadi. Fayllar saqlangan; qayta urining.";
  } finally {
    busy = false;
    retry.disabled = retire.disabled = false;
    status.textContent = "";
  }
});
retry.addEventListener("click", async () => {
  busy = true;
  retry.disabled = retire.disabled = true;
  status.textContent = "Ulanish va saqlangan amallar tekshirilmoqda…";
  try {
    const result = await window.tinConnection.retry();
    if (!result.ok) error.textContent = result.error;
  } catch {
    error.textContent = "Ulanish bajarilmadi. Qayta urining.";
  } finally {
    busy = false;
    retry.disabled = retire.disabled = false;
    status.textContent = "";
  }
});
let state;
async function refreshUpdate() {
  state = await window.tinDesktop.updateStatus();
  document.querySelector("#update").disabled =
    busy || ["checking", "downloading", "installing"].includes(state.phase);
  document.querySelector("#update").textContent =
    state.phase === "ready"
      ? "Qayta ishga tushirib o‘rnatish"
      : "Yangilanishni tekshirish";
  document.querySelector("#update-state").textContent =
    state.error ||
    {
      checking: "Yangilanish tekshirilmoqda…",
      downloading: `${state.version}: ${state.percent}% yuklandi`,
      ready: `${state.version} tayyor.`,
      current: "Oxirgi versiya o‘rnatilgan.",
      installing: "O‘rnatilmoqda…",
    }[state.phase] ||
    `EXE ${state.current}`;
}
document.querySelector("#update").addEventListener("click", async () => {
  const result =
    await window.tinDesktop[
      state?.phase === "ready" ? "installUpdate" : "checkUpdate"
    ]();
  if (!result.ok)
    document.querySelector("#update-state").textContent = result.error;
  else await refreshUpdate();
});
refreshUpdate();
setInterval(refreshUpdate, 2000);
