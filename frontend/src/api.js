const BASE = '/api'

async function handle(response) {
  if (response.status === 204) return null

  let body = null
  try {
    body = await response.json()
  } catch {
  }

  if (!response.ok) {
    const message = body?.error?.message || `Ошибка сервера (${response.status})`
    const error = new Error(message)
    error.code = body?.error?.code
    error.requestId = body?.request_id
    throw error
  }
  return body
}

export async function uploadDocument(file, { checkEnabled = true } = {}) {
  const form = new FormData()
  form.append('file', file)

  const response = await fetch(`${BASE}/documents?check_enabled=${checkEnabled}`, {
    method: 'POST',
    body: form,
  })
  return handle(response)
}

export async function listDocuments() {
  return handle(await fetch(`${BASE}/documents`))
}

export async function getDocumentText(id) {
  return handle(await fetch(`${BASE}/documents/${id}/text`))
}

export async function deleteDocument(id) {
  return handle(await fetch(`${BASE}/documents/${id}`, { method: 'DELETE' }))
}