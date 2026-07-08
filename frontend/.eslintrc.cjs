module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["@typescript-eslint", "react-hooks", "react-refresh"],
  ignorePatterns: [
    "dist",
    "node_modules",
    "*.config.js",
    "*.config.ts",
    "vite.config.d.ts",
    "src/vite-env.d.ts",
  ],
  rules: {},
};
