import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default tseslint.config(
  // public/tracker is MediaPipe's runtime, copied in by scripts/fetch-tracker.mjs.
  { ignores: ["**/dist/**", "**/node_modules/**", "**/schema.d.ts", "**/public/tracker/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // Ground rule 3: the generated types describe every field, so an escape
      // hatch here means the wrong type is being worked around rather than fixed.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
  {
    // Build scripts, run by Node rather than the browser.
    files: ["scripts/**/*.mjs"],
    languageOptions: { globals: globals.node },
  },
  {
    // The component library exports each component's variants beside it, the
    // shadcn shape. Nothing here is a hot-reload boundary of its own: an edit
    // reloads the screen that imports it either way.
    files: ["shared/ui/**/*.tsx"],
    rules: { "react-refresh/only-export-components": "off" },
  },
);
