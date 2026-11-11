/**
 * 30-minute MTP stability run: one qwen9b 16k q4 MTP server, repeated greedy
 * requests, recording tok/s, draft acceptance, free VRAM, power and temperature.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { LocalModelService } from 'file:///E:/Deepseek/packages/dsh-local-model/src/host/server.js'

const SERVER = 'E:\\Deepseek\\tir-b\\runtime\\llama-b12202\\llama-server.exe'
const ROOT = 'E:\\model\\bionic'
const OUT = 'E:\\Deepseek\\tir-b\\test\\mtp-plugin'
const DURATION_MS = Number(process.env.MTP_STABILITY_MS ?? 30 * 60 * 1000)
const INTERVAL_MS = Number(process.env.MTP_STABILITY_INTERVAL_MS ?? 10000)

function nvidia() {
  try {
    const out = execFileSync('nvidia-smi', ['--query-gpu=memory.free,temperature.gpu,power.draw,clocks.mem', '--format=csv,noheader,nounits'], { encoding: 'utf8', timeout: 5000 })
    const [free, temp, power, mclk] = out.trim().split(',').map((part) => Number(part.trim()))
    return { freeMiB: free, tempC: temp, powerW: power, memClockMHz: mclk }
  } catch {
    return null
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function llamaServerCount() {
  try {
    const out = execFileSync('tasklist', ['/FI', 'IMAGENAME eq llama-server.exe', '/FO', 'CSV', '/NH'], { encoding: 'utf8', timeout: 5000 })
    return out.split(/\r?\n/).filter((line) => line.startsWith('"llama-server.exe"')).length
  } catch {
    return 0
  }
}

async function request(port, maxTokens) {
  const started = Date.now()
  const response = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      messages: [{ role: 'user', content: 'The capital of France is' }],
      max_tokens: maxTokens,
      temperature: 0,
      stream: false,
    }),
  })
  const text = await response.text()
  const json = JSON.parse(text)
  return {
    status: response.status,
    tok_s: json?.timings?.predicted_per_second ?? null,
    predicted_n: json?.timings?.predicted_n ?? null,
    wall_s: (Date.now() - started) / 1000,
  }
}

fs.mkdirSync(OUT, { recursive: true })
const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mtp-stability-'))
const service = new LocalModelService({}, {
  modelRoots: [ROOT],
  llamaServerPath: SERVER,
  defaultCtx: 16384,
  defaultKv: 'q8_0',
  minModelBytes: 1024 * 1024 * 1024,
  portRange: [18196, 18210],
  vramReserveMiB: 0,
  allowVramOvercommit: true,
  healthTimeoutMs: 180000,
  logDir,
  mtp: 'auto',
  modelOverrides: [{ match: 'Qwen3.8-9B', ctx: 16384, kv: 'q4_0' }],
})

const samples = []
const startedAt = Date.now()
let errors = 0
let restarts = 0
let status = null
try {
  const models = await service.list()
  const qwen = models.find((model) => model.name.includes('Qwen3.8-9B'))
  status = await service.ensureRunning(qwen.id)
  fs.writeFileSync(path.join(OUT, 'stability-start.json'), JSON.stringify({ startedAt: new Date(startedAt).toISOString(), start: status }, null, 2), 'utf8')

  while (Date.now() - startedAt < DURATION_MS) {
    const iteration = samples.length + 1
    const sample = { iteration, at: new Date().toISOString(), gpu: nvidia() }
    const contention = llamaServerCount() > 1
    if (contention) {
      sample.skipped = 'another llama-server is running (Qoder benchmark); sample skipped'
      samples.push(sample)
      fs.writeFileSync(path.join(OUT, 'stability.jsonl'), samples.map((item) => JSON.stringify(item)).join('\n') + '\n', 'utf8')
      await sleep(INTERVAL_MS)
      continue
    }
    try {
      const response = await request(status.port, 64)
      sample.request = response
      const current = service.status()
      sample.mtp = {
        acceptance: current.mtp?.acceptance ?? null,
        meanLen: current.mtp?.meanLen ?? null,
        fallbackCtx: current.mtp?.fallbackCtx ?? null,
      }
      if (current.mtp?.fallbackCtx !== null && current.mtp?.fallbackCtx !== undefined) {
        sample.warning = `fallback ctx ${current.mtp.fallbackCtx}`
      }
    } catch (error) {
      errors += 1
      sample.error = String(error?.message ?? error)
      if (!service.status().running) {
        sample.serverDown = true
        try {
          status = await service.ensureRunning(qwen.id)
          restarts += 1
          sample.restarted = { pid: status.pid, port: status.port, mtp: status.mtp }
        } catch (restartError) {
          sample.restartError = String(restartError?.message ?? restartError)
        }
      }
    }
    samples.push(sample)
    fs.writeFileSync(path.join(OUT, 'stability.jsonl'), samples.map((item) => JSON.stringify(item)).join('\n') + '\n', 'utf8')
    if (iteration % 6 === 0) {
      const ok = samples.filter((item) => item.request?.tok_s !== null && item.request?.tok_s !== undefined)
      const tok = ok.map((item) => item.request.tok_s)
      const acc = samples.filter((item) => typeof item.mtp?.acceptance === 'number').map((item) => item.mtp.acceptance)
      console.log(JSON.stringify({
        minute: ((Date.now() - startedAt) / 60000).toFixed(1),
        samples: samples.length,
        errors,
        tok_s_avg: tok.length === 0 ? null : Number((tok.reduce((a, b) => a + b, 0) / tok.length).toFixed(1)),
        tok_s_min: tok.length === 0 ? null : Math.min(...tok).toFixed(1),
        tok_s_max: tok.length === 0 ? null : Math.max(...tok).toFixed(1),
        acceptance_avg: acc.length === 0 ? null : Number((acc.reduce((a, b) => a + b, 0) / acc.length).toFixed(3)),
        gpu: sample.gpu,
      }))
    }
    await sleep(INTERVAL_MS)
  }
} finally {
  await service.stop()
  const ok = samples.filter((item) => typeof item.request?.tok_s === 'number')
  const tok = ok.map((item) => item.request.tok_s)
  const acc = samples.filter((item) => typeof item.mtp?.acceptance === 'number').map((item) => item.mtp.acceptance)
  const free = samples.filter((item) => typeof item.gpu?.freeMiB === 'number').map((item) => item.gpu.freeMiB)
  const temps = samples.filter((item) => typeof item.gpu?.tempC === 'number').map((item) => item.gpu.tempC)
  const powers = samples.filter((item) => typeof item.gpu?.powerW === 'number').map((item) => item.gpu.powerW)
  const summary = {
    startedAt: new Date(startedAt).toISOString(),
    finishedAt: new Date().toISOString(),
    duration_min: Number(((Date.now() - startedAt) / 60000).toFixed(1)),
    interval_ms: INTERVAL_MS,
    samples: samples.length,
    skipped_contention: samples.filter((item) => typeof item.skipped === 'string').length,
    errors,
    restarts,
    tok_s: tok.length === 0 ? null : {
      avg: Number((tok.reduce((a, b) => a + b, 0) / tok.length).toFixed(2)),
      min: Number(Math.min(...tok).toFixed(2)),
      max: Number(Math.max(...tok).toFixed(2)),
    },
    acceptance: acc.length === 0 ? null : {
      avg: Number((acc.reduce((a, b) => a + b, 0) / acc.length).toFixed(3)),
      min: Math.min(...acc),
      max: Math.max(...acc),
    },
    free_vram_mib: free.length === 0 ? null : { min: Math.min(...free), max: Math.max(...free) },
    temp_c: temps.length === 0 ? null : { min: Math.min(...temps), max: Math.max(...temps) },
    power_w: powers.length === 0 ? null : { min: Math.min(...powers), max: Math.max(...powers) },
  }
  fs.writeFileSync(path.join(OUT, 'stability-summary.json'), JSON.stringify(summary, null, 2), 'utf8')
  console.log(JSON.stringify({ summary }))
}
