const moduleRef = await import("./dist/automem.plugin.js");

if (typeof moduleRef.AutomemPlugin !== "function") {
  throw new Error("OpenCode adapter is missing AutomemPlugin export");
}

console.log("opencode smoke ok");
