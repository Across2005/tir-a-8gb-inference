/**
 * G2 GUI check: mint the local browser-session cookie from the profile secret,
 * open the DSH Web GUI in headless Edge, list the model selector and screenshot it.
 * Writes only under tir-b/test.
 */
import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const GUI = process.env.DSH_GUI_URL ?? 'http://127.0.0.1:51013'
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const PORT = 9223
const OUT = 'E:\\Deepseek\\tir-b\\test'
const SECRET = 'dgr0ej3SE9Ju4baVzTyeVMLKUh4KIzFpuJwsXusjWO8'

function b64url(buffer) {
  return Buffer.from(buffer).toString('base64').replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '')
}

function makeCookie(authority) {
  const secret = Buffer.from(SECRET, 'base64url')
  const name = 'dsh-auth-' + b64url(crypto.createHash('sha256').update(authority).digest())
  const issuedAt = Date.now()
  const payload = { version: 1, authority, issuedAt, expiresAt: issuedAt + 7 * 86400000 }
  const body = b64url(Buffer.from(JSON.stringify(payload)))
  const sig = b64url(crypto.createHmac('sha256', secret).update(body).digest())
  return { name, value: `v1.${body}.${sig}` }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function json(url, options) {
  const response = await fetch(url, options)
  return response.json()
}

const authority = new URL(GUI).host
const cookie = makeCookie(authority)
console.log(JSON.stringify({ authority, cookieName: cookie.name }))

const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-gui-edge-'))
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
      version = await json(`http://127.0.0.1:${PORT}/json/version`)
      break
    } catch {
      await sleep(500)
    }
  }
  if (version === undefined) throw new Error('edge devtools never became ready')

  const target = await json(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })
  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })

  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id !== undefined && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reject(new Error(JSON.stringify(message.error)))
      else resolve(message.result)
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
  await send('Network.setCookie', {
    name: cookie.name,
    value: cookie.value,
    domain: '127.0.0.1',
    path: '/',
    httpOnly: true,
    sameSite: 'Strict',
  })
  await send('Page.navigate', { url: `${GUI}/` })
  await sleep(5000)

  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    return result.result?.value
  }

  const before = await evaluate('document.body.innerText.slice(0, 3000)')
  fs.writeFileSync(path.join(OUT, 'g2-gui-before.txt'), String(before), 'utf8')

  const buttons = await evaluate(`Array.from(document.querySelectorAll('button')).map((b) => (b.innerText || '').trim()).filter(Boolean).slice(0, 80)`)
  fs.writeFileSync(path.join(OUT, 'g2-gui-buttons.json'), JSON.stringify(buttons, null, 2), 'utf8')

  const clicked = await evaluate(`(() => {
    const buttons = Array.from(document.querySelectorAll('button'))
    const target = buttons.find((b) => /DeepSeek-V4|model|模型|Flash/i.test((b.innerText || '') + (b.getAttribute('aria-label') || '') + (b.title || '')))
    if (target === undefined) return null
    target.click()
    return (target.innerText || target.getAttribute('aria-label') || '').trim()
  })()`)
  await sleep(2500)

  const openedModelMenu = await evaluate(`(() => {
    const items = Array.from(document.querySelectorAll('[role="menuitem"],[role="option"],button,li,div'))
    const target = items.find((el) => {
      const text = (el.innerText || '').trim()
      return text.startsWith('模型') && el.querySelectorAll('*').length < 12
    })
    if (target === undefined) return null
    target.click()
    return (target.innerText || '').trim().slice(0, 80)
  })()`)
  await sleep(2500)

  const probe = await evaluate(`(() => {
    const all = Array.from(document.querySelectorAll('*'))
    const hits = []
    for (const el of all) {
      const text = (el.innerText || '').trim()
      if (text.length > 0 && text.length < 120 && /local|llama|Local|GGUF|Qwen3\\.8-9B|DeepSeek-R1-0528/i.test(text)) hits.push(text)
    }
    return {
      hits: [...new Set(hits)].slice(0, 40),
      menuItems: Array.from(document.querySelectorAll('[role="menuitem"],[role="option"],[role="listitem"]')).map((el) => (el.innerText || '').trim()).filter(Boolean).slice(0, 80),
      hasLocalLlama: document.body.innerHTML.includes('Local llama.cpp'),
    }
  })()`)
  fs.writeFileSync(path.join(OUT, 'g2-gui-probe.json'), JSON.stringify({ openedModelMenu, probe }, null, 2), 'utf8')

  const after = await evaluate('document.body.innerText')
  fs.writeFileSync(path.join(OUT, 'g2-gui-after.txt'), String(after), 'utf8')

  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  const shotPath = path.join(OUT, 'g2-gui.png')
  fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'))
  console.log(JSON.stringify({ clicked, probe, shotPath, beforeLength: String(before).length, afterLength: String(after).length }))
} finally {
  try {
    ws?.close()
  } catch {}
  edge.kill()
  await sleep(1000)
}
