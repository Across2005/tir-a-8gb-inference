import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { LocalModelAdapter } from 'file:///E:/Deepseek/packages/dsh-local-model/src/host/adapter.js'
import { LocalModelService } from 'file:///E:/Deepseek/packages/dsh-local-model/src/host/server.js'

const log = (message) => console.error(`${new Date().toISOString()} ${message}`)
const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-probe-'))
const cfg = {
  modelRoots: ['E:\\model\\bionic'],
  llamaServerPath: 'E:\\Deepseek\\tir-b\\runtime\\llama-b12202\\llama-server.exe',
  defaultCtx: 16384,
  defaultKv: 'q8_0',
  minModelBytes: 1024 * 1024 * 1024,
  portRange: [18160, 18170],
  vramReserveMiB: 0,
  allowVramOvercommit: true,
  logDir,
  modelOverrides: [{ match: 'Qwen3.8-9B', ctx: 4096 }],
}

log(`logDir=${logDir}`)
const service = new LocalModelService({}, cfg)
log(`configErrors=${JSON.stringify(service.configErrors)}`)
const models = await service.list()
log(`models=${models.map((model) => model.name).join(' | ')}`)
const qwen = models.find((model) => model.name.includes('Qwen3.8-9B'))
log(`ensure ${qwen.id}`)
const status = await service.ensureRunning(qwen.id)
log(`running model=${status.model} port=${status.port} pid=${status.pid} effective=${JSON.stringify(status.effective)}`)

const adapter = new LocalModelAdapter(service, cfg)
log('streaming')
let count = 0
let text = ''
for await (const chunk of adapter.stream({
  provider: 'local-llama',
  model: qwen.id,
  messages: [{ role: 'user', content: [{ type: 'text', text: 'hi' }] }],
  maxTokens: 8,
})) {
  count++
  if (chunk.type === 'text-delta') text += chunk.text
  log(`chunk ${chunk.type}`)
}
log(`stream done chunks=${count} text=${JSON.stringify(text)}`)

const dsr = models.find((model) => model.name.includes('DeepSeek-R1'))
log(`switch ${dsr.id}`)
const switched = await service.ensureRunning(dsr.id)
log(`switched model=${switched.model} port=${switched.port}`)
log('stop')
await service.stop()
log('stopped')
process.exit(0)
