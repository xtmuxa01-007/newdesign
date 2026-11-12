// Haqiqiy electron-updater bilan paket SHA512 tekshiruvi. Installer ishga tushmaydi.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const updaterRequire = createRequire(require.resolve('electron-updater'));
const { HttpExecutor } = updaterRequire('builder-util-runtime');
const { ElectronHttpExecutor } = require('electron-updater/out/electronHttpExecutor');
const { NsisUpdater } = require('electron-updater/out/NsisUpdater');

class TestExecutor extends HttpExecutor {
  createRequest(options, callback) {
    return (options.protocol === 'https:' ? https : http).request(options, callback);
  }
}
// Electronning ayni yuklash/hash kodi, tarmoq transporti esa Node bilan.
TestExecutor.prototype.download = ElectronHttpExecutor.prototype.download;

test('real updater downloads redirected file and rejects incorrect SHA512', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tin-update-'));
  const bytes = Buffer.from('MZ TIN test installer: never execute');
  let corrupt = false;
  const server = http.createServer((req, res) => {
    if (req.url.startsWith('/latest.yml')) {
      const digest = crypto.createHash('sha512').update(corrupt ? 'wrong' : bytes).digest('base64');
      res.end(JSON.stringify({version: '0.4.8', files: [{url: 'files/v0.4.8/TIN-CRM-Setup-0.4.8.exe',
        sha512: digest, size: bytes.length}], releaseDate: '2026-09-21T00:00:00Z'}));
    } else if (req.url.startsWith('/files/')) {
      res.writeHead(302, {Location: '/package.exe'}); res.end();
    } else if (req.url === '/package.exe') {
      res.writeHead(200, {'Content-Length': bytes.length}); res.end(bytes);
    } else {res.writeHead(404); res.end();}
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    for (const badHash of [false, true]) {
      corrupt = badHash;
      const folder = path.join(root, badHash ? 'bad' : 'good');
      fs.mkdirSync(folder);
      const config = path.join(folder, 'app-update.yml');
      fs.writeFileSync(config, 'updaterCacheDirName: isolated-cache\n');
      const app = {version: '0.4.7', name: 'TIN-test', isPackaged: true,
        appUpdateConfigPath: config, userDataPath: folder, baseCachePath: folder,
        whenReady: async () => {}, onQuit() {}, quit() {throw Error('Must not install');}, relaunch() {throw Error('Must not install');}};
      const updater = new NsisUpdater(null, app);
      updater.httpExecutor = new TestExecutor();
      updater.logger = {info() {}, warn() {}, error() {}, debug() {}};
      updater.autoDownload = false;
      updater.autoInstallOnAppQuit = false;
      updater.disableDifferentialDownload = true;
      updater.setFeedURL({provider: 'generic', url: `http://127.0.0.1:${server.address().port}/`});
      const result = await updater.checkForUpdates();
      assert.equal(result.updateInfo.version, '0.4.8');
      if (badHash) {
        await assert.rejects(updater.downloadUpdate(), /checksum mismatch/i);
        assert.equal(updater.installerPath, null);
      } else {
        const [file] = await updater.downloadUpdate();
        assert.deepEqual(fs.readFileSync(file), bytes);
      }
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(root, {recursive: true, force: true});
  }
});
