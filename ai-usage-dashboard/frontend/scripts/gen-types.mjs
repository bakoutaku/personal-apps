// 由 contracts/openapi.json 生成 src/api/schema.gen.ts。
// 只是 openapi-typescript 官方生成器的跨平台调用封装：路径用 URL / fileURLToPath，不拼分隔符。
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

const specUrl = new URL('../../contracts/openapi.json', import.meta.url);
const outUrl = new URL('../src/api/schema.gen.ts', import.meta.url);

const spec = JSON.parse(await readFile(specUrl, 'utf8'));
const ast = await openapiTS(spec);
const header =
  '/* 由 scripts/gen-types.mjs 根据 contracts/openapi.json 生成，请勿手改。 */\n';
await writeFile(outUrl, header + astToString(ast), 'utf8');
console.log(`types → ${fileURLToPath(outUrl)} (contract ${spec.info?.version ?? '?'})`);
