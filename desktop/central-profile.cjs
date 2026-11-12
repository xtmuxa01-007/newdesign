// Bu nomni versiya bilan almashtirmang: keyingi yangilanishlarda baza saqlanadi.
const path = require("node:path");
const SERVER = "https://tincrm.uz";
const NAMESPACE = "tincrm-uz-v1";
function centerFolder(legacyFolder) {
  return path.join(legacyFolder, "centers", NAMESPACE);
}
module.exports = { SERVER, NAMESPACE, centerFolder };
