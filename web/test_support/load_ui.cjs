const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadUi(sandbox, directory) {
  const scripts = JSON.parse(fs.readFileSync(path.join(directory, "assets.json"), "utf8"));
  for (const name of scripts) {
    let source = fs.readFileSync(path.join(directory, name), "utf8");
    if (name === "app.js") source = source.replace(/refresh\(\);\s*$/, "");
    vm.runInContext(source, sandbox, { filename: name });
  }
}
module.exports = { loadUi };
