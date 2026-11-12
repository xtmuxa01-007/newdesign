// Yangilanish fonda yuklanadi; o'rnatish foydalanuvchi tugmani bosgandagina.
const FEED = "https://tincrm.uz/api/desktop/updates/";
function createUpdater({ autoUpdater, version, enabled, beforeInstall }) {
  let state = {
    current: version,
    phase: "idle",
    version: null,
    percent: 0,
    error: "",
  };
  let checking = false;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.allowDowngrade = false;
  autoUpdater.allowPrerelease = false;
  // Birinchi versiyalarda eski blockmap yo'q; to'liq paket SHA512 bilan tekshiriladi.
  autoUpdater.disableDifferentialDownload = true;
  autoUpdater.setFeedURL({
    provider: "generic",
    url: FEED,
    useMultipleRangeRequest: false,
  });
  autoUpdater.logger = { info() {}, warn() {}, error() {}, debug() {} };
  const change = (value) => {
    state = { ...state, ...value };
  };
  autoUpdater.on("checking-for-update", () =>
    change({ phase: "checking", error: "" }),
  );
  autoUpdater.on("update-not-available", () =>
    change({ phase: "current", version: null, error: "" }),
  );
  autoUpdater.on("update-available", (info) =>
    change({
      phase: "downloading",
      version: info.version,
      percent: 0,
      error: "",
    }),
  );
  autoUpdater.on("download-progress", (progress) =>
    change({
      phase: "downloading",
      percent: Math.min(100, Math.max(0, Math.round(progress.percent))),
    }),
  );
  autoUpdater.on("update-downloaded", (info) =>
    change({ phase: "ready", version: info.version, percent: 100, error: "" }),
  );
  autoUpdater.on("error", () =>
    change({
      phase: "error",
      error:
        "Yangilanishni tekshirib yoki yuklab bo‘lmadi. Internetni tekshirib qayta urining.",
    }),
  );
  return {
    status: () => ({ ...state }),
    async check() {
      if (!enabled)
        return { ...state, error: "Yangilanish o‘rnatilgan EXEda ishlaydi." };
      if (
        checking ||
        ["downloading", "ready", "installing"].includes(state.phase)
      )
        return { ...state };
      checking = true;
      try {
        const result = await autoUpdater.checkForUpdates();
        // Event error matnini boshqaradi; fondagi Promise unhandled bo'lib qolmasin.
        result?.downloadPromise?.catch(() => {});
      } catch {
        change({
          phase: "error",
          error: "Yangilanish manbasiga ulanib bo‘lmadi. Qayta urining.",
        });
      } finally {
        checking = false;
      }
      return { ...state };
    },
    async install() {
      if (state.phase !== "ready")
        throw new Error("Avval yangi versiya yuklanishini kuting.");
      change({ phase: "installing", error: "" });
      try {
        await beforeInstall();
        autoUpdater.quitAndInstall(true, true);
      } catch (error) {
        change({ phase: "ready", error: error.message });
        throw error;
      }
      return { ...state };
    },
  };
}
module.exports = { createUpdater, FEED };
