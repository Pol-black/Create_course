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

export async function processDocument(id) {
  return handle(await fetch(`${BASE}/documents/${id}/process`, { method: 'POST' }))
}

export async function getChunks(id) {
  return handle(await fetch(`${BASE}/documents/${id}/chunks`))
}

export async function getLog(id) {
  return handle(await fetch(`${BASE}/documents/${id}/log`))
}

// курсы

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const listCourses = async () => handle(await fetch(`${BASE}/courses`))
export const getCourse = async (id) => handle(await fetch(`${BASE}/courses/${id}`))
export const createExampleCourse = async () => handle(await fetch(`${BASE}/courses/example`, { method: 'POST' }))
export const createDraftCourse = async (documentId, replace = false) =>
  handle(await fetch(`${BASE}/documents/${documentId}/course/draft?replace=${replace}`, { method: 'POST' }))
export const updateCourse = async (id, data) => handle(await fetch(`${BASE}/courses/${id}`, json('PATCH', data)))
export const deleteCourse = async (id) => handle(await fetch(`${BASE}/courses/${id}`, { method: 'DELETE' }))
export const reorderSections = async (id, sectionIds) =>
  handle(await fetch(`${BASE}/courses/${id}/order`, json('PUT', { section_ids: sectionIds })))
export const addSection = async (id, title) =>
  handle(await fetch(`${BASE}/courses/${id}/sections`, json('POST', { title })))
export const exportUrl = (id) => `${BASE}/courses/${id}/export.md`

export const updateSection = async (id, data) => handle(await fetch(`${BASE}/sections/${id}`, json('PATCH', data)))
export const deleteSection = async (id) => handle(await fetch(`${BASE}/sections/${id}`, { method: 'DELETE' }))
export const getVersions = async (id) => handle(await fetch(`${BASE}/sections/${id}/versions`))
export const restoreVersion = async (sectionId, versionId) =>
  handle(await fetch(`${BASE}/sections/${sectionId}/versions/${versionId}/restore`, { method: 'POST' }))
export const regenerateSection = async (id, hint) =>
  handle(await fetch(`${BASE}/sections/${id}/regenerate`, json('POST', { hint })))
