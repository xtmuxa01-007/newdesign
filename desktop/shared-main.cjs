// Barcha EXElar web bilan bir xil HTTPS API va markaziy bazadan foydalanadi.
const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { SERVER, centerFolder } = require("./central-profile.cjs");

// O'rnatilgan ilova va bitta nusxa qulfining eski identifikatori saqlanadi.
const profileFolder = process.env.MARVA_DATA_DIR
  ? path.join(path.resolve(process.env.MARVA_DATA_DIR), "desktop-profile")
  : path.join(app.getPath("appData"), "Marva CRM");
fs.mkdirSync(profileFolder, { recursive: true });
app.setPath("userData", profileFolder);
const sessionFolder = path.join(profileFolder, "shared-web");
fs.mkdirSync(sessionFolder, { recursive: true });
app.setPath("sessionData", sessionFolder);
const legacyFolder =
  process.env.MARVA_DATA_DIR || path.join(profileFolder, "branch");
const centerRoot = centerFolder(legacyFolder);
const root = app.isPackaged
  ? process.resourcesPath
  : path.resolve(__dirname, "..");
const binary = app.isPackaged
  ? path.join(root, "backend", "marva-backend.exe")
  : path.join(root, "backend", "dist", "marva-backend", "marva-backend.exe");
const connectionFile = path.join(__dirname, "connection.html");
const connectionURL = pathToFileURL(connectionFile).href;
let window, helper, updater;
let starting = false;
let prepared = false;
let connectionError = "";
let canRetire = false;

function command(flag, directory) {
  return new Promise((resolve) => {
    let output = "",
      settled = false;
    const child = spawn(binary, [flag, "--data-dir", directory], {
      windowsHide: true,
      stdio: ["pipe", "pipe", "ignore"],
    });
    helper = child;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (helper === child) helper = undefined;
      resolve(result);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish({
        ok: false,
        error:
          "Ulanish tugamadi. Eski baza va yuborilmagan amallar saqlangan. Qayta urining.",
      });
    }, 180000);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      output += chunk;
      if (output.length > 1024 * 1024) {
        child.kill();
        finish({ ok: false, error: "Ulanish javobi juda katta." });
      }
    });
    child.once("error", () =>
      finish({
        ok: false,
        error:
          "EXE yordamchi fayli topilmadi. Ilovani qayta o‘rnating; baza papkasini saqlang.",
      }),
    );
    child.once("close", () => {
      try {
        finish(JSON.parse(output.trim()));
      } catch {
        finish({
          ok: false,
          error:
            "Tayyorlash yakunlanmadi. Qayta urining; lokal baza saqlangan.",
        });
      }
    });
    child.stdin.on("error", () => {});
    child.stdin.end("{}");
  });
}

function allowed(url) {
  try {
    return url === connectionURL || new URL(url).origin === SERVER;
  } catch {
    return false;
  }
}

function trusted(event, localOnly = false) {
  if (
    event.sender !== window?.webContents ||
    event.senderFrame !== window.webContents.mainFrame
  )
    return false;
  return localOnly
    ? event.senderFrame.url === connectionURL
    : allowed(event.senderFrame.url);
}

async function connectionPage(message) {
  connectionError = message;
  await window.loadFile(connectionFile);
  window.show();
}

async function openWorkspace() {
  if (starting)
    return { ok: false, error: "Oldingi ulanish tugashini kuting." };
  starting = true;
  try {
    if (!prepared) {
      canRetire = false;
      const center = await command("--prepare-center", legacyFolder);
      if (!center.ok) throw new Error(center.error);
      const online = await command("--prepare-online", centerRoot);
      if (!online.ok) {
        canRetire = online.code === "legacy_device_unavailable";
        throw new Error(online.error);
      }
      prepared = true;
    }
    try {
      await window.loadURL(SERVER);
    } catch {
      throw new Error(
        "Markaziy serverga ulanib bo‘lmadi. Internetni tekshirib qayta urining.",
      );
    }
    window.show();
    window.focus();
    return { ok: true };
  } catch (error) {
    await connectionPage(error.message);
    return { ok: false, error: error.message };
  } finally {
    starting = false;
  }
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      window.restore();
      window.focus();
    }
  });
  app.whenReady().then(async () => {
    try {
      window = new BrowserWindow({
        width: 1440,
        height: 950,
        minWidth: 1000,
        minHeight: 720,
        title: "TIN — Marwa Company",
        autoHideMenuBar: true,
        show: false,
        backgroundColor: "#efe6ce",
        icon: path.join(__dirname, "assets", "tin-icon.ico"),
        webPreferences: {
          nodeIntegration: false,
          contextIsolation: true,
          sandbox: true,
          // Lokal IDli eski savatlar yangi markaziy savdoga aralashmaydi.
          partition: "persist:tincrm-shared-web-v1",
          preload: path.join(__dirname, "preload.cjs"),
        },
      });
      window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      window.webContents.session.setPermissionRequestHandler(
        (_web, _permission, callback) => callback(false),
      );
      for (const eventName of ["will-navigate", "will-redirect"]) {
        window.webContents.on(eventName, (event, url) => {
          if (!allowed(url)) event.preventDefault();
        });
      }
      window.webContents.on(
        "did-fail-load",
        (_event, code, _description, _url, mainFrame) => {
          if (mainFrame && code !== -3 && !starting)
            connectionPage(
              "Serverga aloqa uzildi. Internet tiklangach qayta urining.",
            ).catch(() => {});
        },
      );
      ipcMain.handle("online-info", (event) =>
        trusted(event, true)
          ? { server: SERVER, error: connectionError, canRetire }
          : null,
      );
      ipcMain.handle("online-retry", (event) =>
        trusted(event, true)
          ? openWorkspace()
          : { ok: false, error: "Ushbu oynadan ulanish bajarilmaydi." },
      );
      ipcMain.handle("online-retire", async (event) => {
        if (!trusted(event, true) || !canRetire || starting)
          return { ok: false, error: "Bu oynada tiklashni bajarib bo‘lmaydi." };
        starting = true;
        let result;
        try {
          result = await command("--retire-center", centerRoot);
        } finally {
          starting = false;
        }
        if (!result.ok) return result;
        prepared = false;
        canRetire = false;
        return openWorkspace();
      });
      const { createUpdater } = require("./updater.cjs");
      updater = createUpdater({
        autoUpdater: require("electron-updater").autoUpdater,
        version: app.getVersion(),
        enabled: app.isPackaged,
        beforeInstall: async () => {
          if (starting || helper)
            throw new Error("Avval joriy ulanish tugashini kuting.");
          const backup = await command("--profile-backup", centerRoot);
          if (!backup.ok) throw new Error(backup.error);
        },
      });
      for (const [channel, action] of [
        ["update-status", "status"],
        ["update-check", "check"],
        ["update-install", "install"],
      ]) {
        ipcMain.handle(channel, async (event) => {
          if (!trusted(event))
            return { ok: false, error: "Ushbu oynadan amal bajarilmaydi." };
          try {
            return { ok: true, ...(await updater[action]()) };
          } catch (error) {
            return { ok: false, error: error.message };
          }
        });
      }
      await openWorkspace();
      const firstCheck = setTimeout(() => updater.check(), 20000);
      const periodicCheck = setInterval(
        () => updater.check(),
        4 * 60 * 60 * 1000,
      );
      firstCheck.unref();
      periodicCheck.unref();
    } catch (error) {
      dialog.showErrorBox("TIN CRM", error.message);
      app.quit();
    }
  });
}
app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  if (helper) helper.kill();
});
