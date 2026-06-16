import fs from "node:fs";
import path from "node:path";

const version = process.argv[2]?.replace(/^v/, "");

if (!version || !/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(version)) {
  console.error("Usage: node scripts/set-version.mjs <semver>");
  process.exit(1);
}

const root = process.cwd();

function writeJson(file, update) {
  const fullPath = path.join(root, file);
  const data = JSON.parse(fs.readFileSync(fullPath, "utf8"));
  update(data);
  fs.writeFileSync(fullPath, `${JSON.stringify(data, null, 2)}\n`);
}

fs.writeFileSync(path.join(root, "VERSION"), `${version}\n`);

writeJson("frontend/package.json", (data) => {
  data.version = version;
});

writeJson("frontend/package-lock.json", (data) => {
  data.version = version;
  if (data.packages?.[""]) {
    data.packages[""].version = version;
  }
});

fs.writeFileSync(
  path.join(root, "backend/app/version.py"),
  `"""Application version."""\n\n__version__ = "${version}"\n`,
);

console.log(`Version set to ${version}`);
