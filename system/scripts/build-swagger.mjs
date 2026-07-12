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

// Swagger UI resolves even document-local $ref values against the current page URL.
// That fails when this self-contained file is opened directly with file://, so expand
// all local references before embedding the specification in the HTML.
const resolveJsonPointer = (document, reference) => {
  if (!reference.startsWith("#/")) {
    throw new Error(`Only document-local OpenAPI references are supported: ${reference}`);
  }
  return reference
    .slice(2)
    .split("/")
    .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
    .reduce((value, part) => value?.[part], document);
};

const dereference = (value, document, activeReferences = new Set()) => {
  if (Array.isArray(value)) {
    return value.map((item) => dereference(item, document, activeReferences));
  }
  if (!value || typeof value !== "object") return value;

  if (typeof value.$ref === "string") {
    const reference = value.$ref;
    if (activeReferences.has(reference)) {
      throw new Error(`Circular OpenAPI reference cannot be embedded for file:// use: ${reference}`);
    }
    const target = resolveJsonPointer(document, reference);
    if (target === undefined) throw new Error(`Unresolved OpenAPI reference: ${reference}`);

    const nextReferences = new Set(activeReferences).add(reference);
    const { $ref: _ignored, ...siblings } = value;
    return {
      ...dereference(target, document, nextReferences),
      ...dereference(siblings, document, nextReferences),
    };
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, dereference(item, document, activeReferences)]),
  );
};

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

const specification = JSON.stringify(dereference(openapi, openapi)).replaceAll("</", "<\\/");
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
