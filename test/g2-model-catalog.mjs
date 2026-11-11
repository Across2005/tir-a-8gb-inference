/**
 * Query the live DSH model catalog with a minted cookie and the client-request envelope.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'

const GUI = 'http://127.0.0.1:51013'
const AUTHORITY = new URL(GUI).host
const SECRET = 'dgr0ej3SE9Ju4baVzTyeVMLKUh4KIzFpuJwsXusjWO8'
const b64url = (b) => Buffer.from(b).toString('base64').replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '')
const secret = Buffer.from(SECRET, 'base64url')
const name = 'dsh-auth-' + b64url(crypto.createHash('sha256').update(AUTHORITY).digest())
const issuedAt = Date.now()
const body = b64url(Buffer.from(JSON.stringify({ version: 1, authority: AUTHORITY, issuedAt, expiresAt: issuedAt + 7 * 86400000 })))
const cookie = `${name}=v1.${body}.${b64url(crypto.createHmac('sha256', secret).update(body).digest())}`

const envelope = {
  type: 'client-request',
  rpcId: crypto.randomUUID(),
  method: 'session/modelCatalog',
  payload: { args: {} },
}
const response = await fetch(`${GUI}/api/session/modelCatalog`, {
  method: 'POST',
  headers: { 'content-type': 'application/json', cookie },
  body: JSON.stringify(envelope),
})
const text = await response.text()
fs.writeFileSync('E:\\Deepseek\\tir-b\\test\\g2-model-catalog.json', text, 'utf8')
const parsed = JSON.parse(text)
const providers = parsed?.result?.value ?? parsed?.result ?? parsed
console.log(JSON.stringify({ status: response.status, length: text.length, hasLocalLlama: text.includes('local-llama') }))
console.log(JSON.stringify(providers, null, 2).slice(0, 8000))
