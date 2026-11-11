/**
 * G2 GUI evidence: authenticate, open the DSH GUI, capture the client API traffic,
 * and look for the local-llama provider/model catalog in the live responses.
 */
import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const GUI = 'http://127.0.0.1:51013'
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const PORT = 9224
const OUT = 'E:\\Deepseek\\tir-b\\test'
const SECRET = 'dgr0ej3SE9Ju4baVzTyeVMLKUh4KIzFpuJwsXusjWO8'
const AUTHORITY = new URL(GUI).host

const b64url = (b) => Buffer.from(b).toString('base64').replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '')
const secret = Buffer.from(SECRET, 'base64url')
const cookieName = 'dsh-auth-' + b64url(crypto.createHash('sha256').update(AUTHORITY).digest())
const issuedAt = Date.now()
const body = b64url(Buffer.from(JSON.stringify({ version: 1, authority: AUTHORITY, issuedAt, expiresAt: issuedAt + 7 * 86400000 })))
const cookieValue = `v1.${body}.${b64url(crypto.createHmac('sha256', secret).update(body).digest())}`

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-gui-edge2-'))
const edge = spawn(EDGE, [
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${userData}`,
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  'about:blank',
], { stdio: 'ignore', windowsHide: true })

let ws
try {
  let version
  for (let i = 0; i < 60; i++) {
    try {
      version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()
      break
    } catch {
      await sleep(500)
    }
  }
  if (version === undefined) throw new Error('edge devtools never became ready')
  const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })

  let id = 0
  const pending = new Map()
  const frames = []
  const requests = []
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id !== undefined && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reject(new Error(JSON.stringify(message.error)))
      else resolve(message.result)
      return
    }
    if (message.method === 'Network.webSocketFrameReceived') {
      const payload = message.params?.response?.payloadData ?? ''
      if (payload.length < 200000) frames.push(payload)
    }
    if (message.method === 'Network.requestWillBeSent') {
      requests.push({ url: message.params.request.url, method: message.params.request.method, postData: message.params.request.postData ?? null })
    }
  })
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const requestId = ++id
      pending.set(requestId, { resolve, reject })
      ws.send(JSON.stringify({ id: requestId, method, params }))
    })

  await send('Page.enable')
  await send('Network.enable')
  await send('Network.setCookie', { name: cookieName, value: cookieValue, domain: '127.0.0.1', path: '/', httpOnly: true, sameSite: 'Strict' })
  await send('Page.navigate', { url: `${GUI}/` })
  await sleep(6000)

  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    return result.result?.value
  }
  // open the model selector so the client asks the host for the catalog
  await evaluate(`(() => {
    const buttons = Array.from(document.querySelectorAll('button'))
    const target = buttons.find((b) => /DeepSeek-V4|Flash/i.test(b.innerText || ''))
    if (target) target.click()
    return Boolean(target)
  })()`)
  await sleep(1500)
  await evaluate(`(() => {
    const items = Array.from(document.querySelectorAll('[role="menuitem"],[role="option"],button,li,div'))
    const target = items.find((el) => (el.innerText || '').trim().startsWith('模型') && el.querySelectorAll('*').length < 12)
    if (target) target.click()
    return Boolean(target)
  })()`)
  await sleep(5000)

  const matched = frames.filter((payload) => /local-llama|Local llama|Qwen3\\.8-9B|Qwen3.8-9B|DeepSeek-R1-0528/i.test(payload))
  const matchedRequests = requests.filter((request) => /model|llm|local/i.test(request.url))
  fs.writeFileSync(path.join(OUT, 'g2-gui-ws-matched.json'), JSON.stringify({ matched, requests: matchedRequests }, null, 2), 'utf8')
  fs.writeFileSync(path.join(OUT, 'g2-gui-ws-all.txt'), frames.join('\n'), 'utf8')
  console.log(JSON.stringify({ frameCount: frames.length, matchedCount: matched.length, matchedRequests: matchedRequests.slice(0, 20), sample: matched.slice(0, 2) }))
} finally {
  try {
    ws?.close()
  } catch {}
  edge.kill()
  await sleep(1000)
}

