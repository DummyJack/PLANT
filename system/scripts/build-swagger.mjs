import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const systemDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectDir = resolve(systemDir, "..");
const swaggerDist = resolve(systemDir, "node_modules/swagger-ui-dist");

const [yamlSource, cssSource, bundleSource, presetSource] = await Promise.all([
  readFile(resolve(projectDir, "server/swagger.yml"), "utf8"),
  readFile(resolve(swaggerDist, "swagger-ui.css"), "utf8"),
  readFile(resolve(swaggerDist, "swagger-ui-bundle.js"), "utf8"),
  readFile(resolve(swaggerDist, "swagger-ui-standalone-preset.js"), "utf8"),
]);

const openapi = parse(yamlSource);
const excludedTags = new Set(["Bootstrap", "Health", "Public Manual"]);

openapi.tags = (openapi.tags ?? []).filter((tag) => !excludedTags.has(tag.name));
delete openapi.security;
if (openapi.components?.securitySchemes) {
  delete openapi.components.securitySchemes;
}
for (const [path, pathItem] of Object.entries(openapi.paths ?? {})) {
  const operations = Object.values(pathItem).filter(
    (operation) => operation && typeof operation === "object" && Array.isArray(operation.tags),
  );
  for (const operation of operations) {
    delete operation.security;
  }
  if (
    operations.length > 0 &&
    operations.every((operation) => operation.tags.some((tag) => excludedTags.has(tag)))
  ) {
    delete openapi.paths[path];
  }
}

const specification = JSON.stringify(openapi).replaceAll("</", "<\\/");
const css = cssSource.replaceAll("</style", "<\\/style");
// Live Server injects its reload client before the first literal </body> it finds.
// Escape only document-closing strings; replacing every </ would corrupt JS regexes.
const escapeEmbeddedDocumentTags = (source) =>
  source
    .replaceAll("</script", "<\\/script")
    .replaceAll("</body", "<\\/body")
    .replaceAll("</head", "<\\/head")
    .replaceAll("</html", "<\\/html");
const bundle = escapeEmbeddedDocumentTags(bundleSource);
const preset = escapeEmbeddedDocumentTags(presetSource);

const html = `<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PLANT System API</title>
    <style>
      ${css}
      .swagger-ui .topbar .download-url-wrapper { display: none; }
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script>${bundle}</script>
    <script>${preset}</script>
    <script>
      window.onload = () => {
        SwaggerUIBundle({
          spec: ${specification},
          dom_id: "#swagger-ui",
          deepLinking: true,
          displayRequestDuration: true,
          filter: false,
          validatorUrl: null,
          withCredentials: true,
          presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
          layout: "StandaloneLayout"
        });
      };
    </script>
  </body>
</html>
`;

const output = resolve(projectDir, "server/swagger.html");
await writeFile(output, html, "utf8");
console.log(`Generated ${output}`);
