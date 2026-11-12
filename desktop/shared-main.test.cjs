const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");
const { pathToFileURL } = require("node:url");
const { SERVER } = require("./central-profile.cjs");

async function launch(failAt, retireFails = false) {
  const paths = { appData: path.resolve("fixture-appdata") };
  const commands = [],
    handlers = {},
    events = {},
    errors = [];
  let ready, opened, window, options;
  const app = {
    isPackaged: true,
    getVersion: () => "0.5.0",
    getPath: (key) => paths[key],
    setPath: (key, value) => {
      paths[key] = value;
    },
    requestSingleInstanceLock: () => true,
    whenReady: () => ({
      then: (fn) => {
        ready = Promise.resolve().then(fn);
      },
    }),
    on() {},
    quit() {},
  };
  class Window {
    constructor(value) {
      options = value;
      window = this;
      this.webContents = {
        mainFrame: { url: "" },
        on: (name, fn) => {
          events[name] = fn;
        },
        setWindowOpenHandler() {},
        session: { setPermissionRequestHandler() {} },
      };
    }
    async loadURL(url) {
      opened = url;
      this.webContents.mainFrame.url = url;
    }
    async loadFile(file) {
      opened = file;
      this.webContents.mainFrame.url = pathToFileURL(file).href;
    }
    show() {}
    focus() {}
  }
  function spawn(_binary, args, config) {
    commands.push(args);
    assert.equal(config.windowsHide, true);
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stdout.setEncoding = () => {};
    child.stdin = new EventEmitter();
    child.kill = () => {};
    child.stdin.end = () =>
      queueMicrotask(() => {
        child.stdout.emit(
          "data",
          JSON.stringify({
            ok:
              args[0] !== failAt &&
              !(args[0] === "--retire-center" && retireFails),
            error: "Fixture unavailable",
            code:
              args[0] === "--prepare-online"
                ? "legacy_device_unavailable"
                : null,
          }),
        );
        if (args[0] === "--retire-center" && !retireFails) failAt = null;
        child.emit("close");
      });
    return child;
  }
  const modules = {
    electron: {
      app,
      BrowserWindow: Window,
      ipcMain: {
        handle: (name, fn) => {
          handlers[name] = fn;
        },
      },
      dialog: { showErrorBox: (_title, message) => errors.push(message) },
    },
    "node:fs": { mkdirSync() {} },
    "node:child_process": { spawn },
    "./central-profile.cjs": require("./central-profile.cjs"),
    "./updater.cjs": require("./updater.cjs"),
    "electron-updater": {
      autoUpdater: Object.assign(new EventEmitter(), { setFeedURL() {} }),
    },
  };
  const entry = JSON.parse(
    fs.readFileSync(path.join(__dirname, "package.json"), "utf8"),
  ).main;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, entry), "utf8"), {
    require: (name) => modules[name] || require(name),
    __dirname,
    process: { env: {}, resourcesPath: path.resolve("fixture-resources") },
    setTimeout,
    clearTimeout,
    setInterval,
    URL,
  });
  await ready;
  return { commands, handlers, events, errors, paths, opened, options, window };
}

test("Packaged entry opens the same server on every PC without a local sales backend or device claim", async () => {
  const a = await launch(),
    b = await launch();
  for (const state of [a, b]) {
    assert.equal(state.opened, SERVER);
    assert.deepEqual(
      state.commands.map((args) => args[0]),
      ["--prepare-center", "--prepare-online"],
    );
    assert.equal(
      state.options.webPreferences.partition,
      "persist:tincrm-shared-web-v1",
    );
    assert.equal(state.options.webPreferences.nodeIntegration, false);
    assert.equal(state.options.webPreferences.sandbox, true);
    assert.equal(state.options.webPreferences.contextIsolation, true);
    assert.notEqual(state.paths.sessionData, state.paths.userData);
    assert.deepEqual(state.errors, []);
  }
});

test("Backup, pending sync, or network failure leaves a retry page and never runs local sales", async () => {
  for (const flag of ["--prepare-center", "--prepare-online"]) {
    const state = await launch(flag);
    assert.ok(state.opened.endsWith("connection.html"));
    const info = state.handlers["online-info"]({
      sender: state.window.webContents,
      senderFrame: state.window.webContents.mainFrame,
    });
    assert.equal(info.error, "Fixture unavailable");
    assert.ok(state.commands.every((args) => args[0] !== "--data-dir"));
  }
});

test("Remote redirects and untrusted frames cannot invoke migration or installer operations", async () => {
  const state = await launch();
  for (const name of ["will-navigate", "will-redirect"]) {
    let prevented = false;
    state.events[name](
      {
        preventDefault() {
          prevented = true;
        },
      },
      "https://untrusted.example/",
    );
    assert.equal(prevented, true);
    prevented = false;
    state.events[name](
      {
        preventDefault() {
          prevented = true;
        },
      },
      SERVER + "/api/sales/export",
    );
    assert.equal(prevented, false);
  }
  const frame = { url: SERVER };
  const result = await state.handlers["update-install"]({
    sender: state.window.webContents,
    senderFrame: frame,
  });
  assert.equal(result.ok, false);
  assert.equal(
    state.handlers["online-info"]({
      sender: state.window.webContents,
      senderFrame: state.window.webContents.mainFrame,
    }),
    null,
  );
  const retry = await state.handlers["online-retry"]({ senderFrame: frame });
  assert.equal(retry.ok, false);
  assert.equal(state.commands.length, 2);
});

test("Rejected device recovery is local-only and opens shared web only after backup succeeds", async () => {
  for (const fails of [true, false]) {
    const state = await launch("--prepare-online", fails);
    const event = {
      sender: state.window.webContents,
      senderFrame: state.window.webContents.mainFrame,
    };
    assert.equal(state.handlers["online-info"](event).canRetire, true);
    assert.equal(
      (await state.handlers["online-retire"]({ senderFrame: { url: SERVER } }))
        .ok,
      false,
    );
    const result = await state.handlers["online-retire"](event);
    assert.equal(result.ok, !fails);
    assert.equal(state.window.webContents.mainFrame.url === SERVER, !fails);
    assert.deepEqual(
      state.commands.map((a) => a[0]),
      fails
        ? ["--prepare-center", "--prepare-online", "--retire-center"]
        : [
            "--prepare-center",
            "--prepare-online",
            "--retire-center",
            "--prepare-center",
            "--prepare-online",
          ],
    );
  }
  const healthy = await launch();
  assert.equal(
    (
      await healthy.handlers["online-retire"]({
        sender: healthy.window.webContents,
        senderFrame: healthy.window.webContents.mainFrame,
      })
    ).ok,
    false,
  );
});
