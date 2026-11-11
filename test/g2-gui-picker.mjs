/**
 * Drive the DSH model picker with real pointer events and report what it offers.
 */
import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const GUI = 'http://127.0.0.1:51013'
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const PORT = 9225
const OUT = 'E:\\Deepseek\\tir-b\\test'
const SECRET = 'dgr0ej3SE9Ju4baVzTyeVMLKUh4KIzFpuJwsXusjWO8'
const AUTHORITY = new URL(GUI).host
const b64url = (b) => Buffer.from(b).toString('base64').replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '')
const secret = Buffer.from(SECRET, 'base64url')
const cookieName = 'dsh-auth-' + b64url(crypto.createHash('sha256').update(AUTHORITY).digest())
const issuedAt = Date.now()
const body = b64url(Buffer.from(JSON.stringify({ version: 1, authority: AUTHORITY, issuedAt, expiresAt: issuedAt + 7 * 86400000 })))
const cookieValue = `v1.${body}.${b64url(crypto.createHmac('sha256', secret).update(body).digest())}`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-picker-'))
const edge = spawn(EDGE, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${userData}`, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', 'about:blank'], { stdio: 'ignore', windowsHide: true })
let ws
const reports = []
try {
  let version
  for (let i = 0; i < 60; i++) {
    try { version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); break } catch { await sleep(500) }
  }
  if (version === undefined) throw new Error('devtools not ready')
  const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }) })
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
  const send = (method, params = {}) => new Promise((resolve, reject) => { const requestId = ++id; pending.set(requestId, { resolve, reject }); ws.send(JSON.stringify({ id: requestId, method, params })) })
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value

  await send('Page.enable')
  await send('Network.enable')
  await send('Network.setCookie', { name: cookieName, value: cookieValue, domain: '127.0.0.1', path: '/', httpOnly: true, sameSite: 'Strict' })
  await send('Page.navigate', { url: `${GUI}/` })
  await sleep(6000)

  const findRect = (regexSource) => evaluate(`(() => {
    const re = new RegExp(${JSON.stringify(regexSource)})
    const pick = (selector) => {
      let best = null
      for (const el of Array.from(document.querySelectorAll(selector))) {
        const text = (el.innerText || '').trim()
        if (!re.test(text) || text.length > 200) continue
        const r = el.getBoundingClientRect()
        if (r.width < 4 || r.height < 4) continue
        const area = r.width * r.height
        if (best === null || area < best.area) best = { text: text.slice(0, 80), x: r.x + r.width / 2, y: r.y + r.height / 2, area }
      }
      return best
    }
    return pick('button,[role="button"],[role="menuitem"],[role="option"]') ?? pick('li,[role="listitem"],div,span')
  })()`)
  const clickAt = async (x, y) => {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y })
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
  }
  const dumpMenu = async (label) => {
    const data = await evaluate(`(() => {
      const items = Array.from(document.querySelectorAll('[role="menuitem"],[role="option"],[role="listitem"]'))
        .map((el) => (el.innerText || '').trim()).filter(Boolean)
      return { items: items.slice(0, 100), bodyTail: document.body.innerText.slice(-1500) }
    })()`)
    reports.push({ label, ...data })
    return data
  }

  const modelButton = await findRect('DeepSeek-V4|Flash')
  reports.push({ label: 'modelButton', modelButton })
  if (modelButton !== null) {
    await clickAt(modelButton.x, modelButton.y)
    await sleep(1200)
    const menu = await dumpMenu('first-menu')
    const modelRow = await findRect('^模型')
    reports.push({ label: 'modelRow', modelRow })
    if (modelRow !== null) {
      await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: modelRow.x, y: modelRow.y })
      await sleep(1500)
      await dumpMenu('hover-submenu')
      const local = await findRect('Local llama|llama\\.cpp|本地')
      reports.push({ label: 'localProvider', local })
      if (local !== null) {
        await clickAt(local.x, local.y)
        await sleep(1500)
        await dumpMenu('model-list')
        const qwen = await findRect('Qwen3\\.8-9B')
        reports.push({ label: 'qwenModel', qwen })
      }
    }
    await send('Page.captureScreenshot', { format: 'png' }).then((shot) => fs.writeFileSync(path.join(OUT, 'g2-gui-picker.png'), Buffer.from(shot.data, 'base64')))
  }
  console.log(JSON.stringify(reports, null, 2).slice(0, 12000))
} finally {
  try { ws?.close() } catch {}
  edge.kill()
  await sleep(800)
}

