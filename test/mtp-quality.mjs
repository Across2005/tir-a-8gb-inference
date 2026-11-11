/**
 * Greedy quality comparison MTP off vs on (same model/ctx/KV/prompt).
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { LocalModelService } from 'file:///E:/Deepseek/packages/dsh-local-model/src/host/server.js'

const SERVER = 'E:\\Deepseek\\tir-b\\runtime\\llama-b12202\\llama-server.exe'
const OUT = 'E:\\Deepseek\\tir-b\\test\\mtp-plugin'

async function run(mtpMode) {
  const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mtp-quality-'))
  const service = new LocalModelService({}, {
    modelRoots: ['E:\\model\\bionic'],
    llamaServerPath: SERVER,
    defaultCtx: 16384,
    defaultKv: 'q8_0',
    minModelBytes: 1024 * 1024 * 1024,
    portRange: [18211, 18225],
    vramReserveMiB: 0,
    allowVramOvercommit: true,
    healthTimeoutMs: 180000,
    logDir,
    mtp: mtpMode,
    modelOverrides: [{ match: 'Qwen3.8-9B', ctx: 16384, kv: 'q4_0' }],
  })
  try {
    const models = await service.list()
    const qwen = models.find((model) => model.name.includes('Qwen3.8-9B'))
    const status = await service.ensureRunning(qwen.id)
    const response = await fetch(`http://127.0.0.1:${status.port}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'Write one short sentence about the capital of France.' }],
        max_tokens: 128,
        temperature: 0,
        stream: false,
      }),
    })
    const json = await response.json()
    const message = json?.choices?.[0]?.message ?? {}
    return {
      mtp: status.mtp,
      content: message.content ?? '',
      reasoning: message.reasoning_content ?? '',
      tok_s: json?.timings?.predicted_per_second ?? null,
      predicted_n: json?.timings?.predicted_n ?? null,
      finish: json?.choices?.[0]?.finish_reason ?? null,
    }
  } finally {
    await service.stop()
  }
}

const off = await run('off')
const on = await run('on')
const offText = (off.reasoning || '') + (off.content || '')
const onText = (on.reasoning || '') + (on.content || '')
const same = offText === onText
let firstDiff = -1
const limit = Math.min(off.content.length, on.content.length)
for (let i = 0; i < limit; i++) {
  if (offText[i] !== onText[i]) { firstDiff = i; break }
}
const result = {
  date: new Date().toISOString(),
  modelConfigured: 'Qwen3.8-9B-Q5_K_M 16k q4_0 greedy',
  off: { ...off, content: off.content.slice(0, 200) },
  on: { ...on, content: on.content.slice(0, 200) },
  identicalText: same,
  firstDiff,
  offChars: offText.length,
  onChars: onText.length,
  offReasoningChars: off.reasoning.length,
  onReasoningChars: on.reasoning.length,
}
fs.mkdirSync(OUT, { recursive: true })
fs.writeFileSync(path.join(OUT, 'quality-mtp-vs-off.json'), JSON.stringify(result, null, 2), 'utf8')
console.log(JSON.stringify({
  identicalText: same,
  firstDiff,
  offChars: offText.length,
  onChars: onText.length,
  offReasoningChars: off.reasoning.length,
  onReasoningChars: on.reasoning.length,
  offTokS: off.tok_s,
  onTokS: on.tok_s,
  offMtp: off.mtp.enabled,
  onMtp: on.mtp.enabled,
}))


