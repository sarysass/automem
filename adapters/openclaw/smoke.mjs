import plugin from "./dist/index.js";

if (!plugin || typeof plugin !== "object") {
  throw new Error("OpenClaw adapter did not export a plugin object");
}

if (plugin.id !== "automem-memory") {
  throw new Error(`Unexpected OpenClaw plugin id: ${String(plugin.id)}`);
}

if (typeof plugin.register !== "function") {
  throw new Error("OpenClaw adapter is missing register()");
}

console.log("openclaw smoke ok");
