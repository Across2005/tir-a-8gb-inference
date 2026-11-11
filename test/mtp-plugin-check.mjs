/**
 * MTP plugin verification against the real llama-server.
 * Starts qwen9b at 16k q4 (MTP) and 2k q8 (MTP), then dsr1 (no MTP), and
 * reports timings.predicted_per_second plus the parsed draft acceptance.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { LocalModelService } from 'file:///E:/Deepseek/packages/dsh-local-model/src/host/server.js'

const SERVER = 'E:\\Deepseek\\tir-b\\runtime\\llama-b12202\\llama-server.exe'
const ROOT = 'E:\\model\\bionic'
const OUT = 'E:\\Deepseek\\tir-b\\test\\mtp-plugin'

function baseConfig(overrides = {}) {
  const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mtp-plugin-'))
  return {
    modelRoots: [ROOT],
    llamaServerPath: SERVER,
    defaultCtx: 16384,
    defaultKv: 'q8_0',
    minModelBytes: 1024 * 1024 * 1024,
    portRange: [18180, 18195],
    vramReserveMiB: 0,
    allowVramOvercommit: true,
    healthTimeoutMs: 180000,
    logDir,
    mtp: 'auto',
    ...overrides,
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function request(port, maxTokens) {
  const body = {
    messages: [{ role: 'user', content: 'The capital of France is' }],
    max_tokens: maxTokens,
    temperature: 0,
    stream: false,
  }
  const started = Date.now()
  const response = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  const text = await response.text()
  let json = null
  try {
    json = JSON.parse(text)
  } catch {
    /* keep raw text */
  }
  return {
    status: response.status,
    wall_s: (Date.now() - started) / 1000,
    predicted_per_second: json?.timings?.predicted_per_second ?? null,
    prompt_per_second: json?.timings?.prompt_per_second ?? null,
    predicted_n: json?.timings?.predicted_n ?? null,
    content: (json?.choices?.[0]?.message?.content ?? '').slice(0, 80),
    raw: json === null ? text.slice(0, 300) : null,
  }
}

async function runScenario(name, config, modelMatch, maxTokens) {
  const service = new LocalModelService({}, config)
  const result = { name, config: { ctx: config.defaultCtx, kv: config.defaultKv, mtp: config.mtp } }
  try {
    const models = await service.list()
    const entry = models.find((model) => model.name.includes(modelMatch))
    if (entry === undefined) throw new Error(`model not found: ${modelMatch}`)
    result.entry = { id: entry.id, mtp: entry.mtp, nextn: entry.nextnLayers, sizeBytes: entry.sizeBytes }
    const status = await service.ensureRunning(entry.id)
    result.start = { pid: status.pid, port: status.port, mtp: status.mtp, vram: status.vram, effective: status.effective }
    result.request = await request(status.port, maxTokens)
    await sleep(800)
    const after = service.status()
    result.mtpAfter = after.mtp
    result.log = await service.logsTail(30)
    return result
  } catch (error) {
    result.error = String(error?.message ?? error)
    try {
      result.log = await service.logsTail(40)
    } catch {
      /* ignore */
    }
    return result
  } finally {
    await service.stop()
  }
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const results = {}

  results.qwen16k = await runScenario(
    'qwen9b 16k q4 MTP',
    baseConfig({
      defaultCtx: 16384,
      defaultKv: 'q8_0',
      modelOverrides: [{ match: 'Qwen3.8-9B', ctx: 16384, kv: 'q4_0' }],
    }),
    'Qwen3.8-9B',
    128,
  )

  results.qwen2k = await runScenario(
    'qwen9b 2k q8 MTP',
    baseConfig({
      defaultCtx: 2048,
      defaultKv: 'q8_0',
      modelOverrides: [{ match: 'Qwen3.8-9B', ctx: 2048, kv: 'q8_0' }],
    }),
    'Qwen3.8-9B',
    128,
  )

  results.dsr1 = await runScenario(
    'dsr1-8b (no MTP head)',
    baseConfig({ defaultCtx: 8192, defaultKv: 'q4_0' }),
    'DeepSeek-R1-0528',
    32,
  )

  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2), 'utf8')
  for (const [key, value] of Object.entries(results)) {
    console.log(JSON.stringify({
      scenario: key,
      entry: value.entry,
      startMtp: value.start?.mtp,
      vram: value.start?.vram,
      request: value.request && {
        status: value.request.status,
        tok_s: value.request.predicted_per_second,
        predicted_n: value.request.predicted_n,
        wall_s: value.request.wall_s,
      },
      mtpAfter: value.mtpAfter && {
        enabled: value.mtpAfter.enabled,
        acceptance: value.mtpAfter.acceptance,
        meanLen: value.mtpAfter.meanLen,
        fallbackCtx: value.mtpAfter.fallbackCtx,
      },
      error: value.error,
    }))
  }
}

await main()
