<script setup>
import { onMounted, ref } from 'vue'
import UploadForm from './components/UploadForm.vue'
import DocumentList from './components/DocumentList.vue'
import { getDocumentText, listDocuments } from './api.js'

const documents = ref([])
const loadError = ref('')
const notice = ref('')
const preview = ref(null) // { file_name, text } — что показываем внизу

async function refresh() {
  loadError.value = ''
  try {
    documents.value = await listDocuments()
  } catch (e) {
    loadError.value = `Не удалось получить список документов: ${e.message}`
  }
}

onMounted(refresh)

async function onUploaded(doc) {
  notice.value =
    doc.status === 'PROCESSED'
      ? `Готово: из файла «${doc.file_name}» извлечено ${doc.text_length} символов`
      : `Файл «${doc.file_name}» загружен, но текст извлечь не удалось`
  await refresh()
  if (doc.status === 'PROCESSED') showText(doc)
}

async function showText(doc) {
  const data = await getDocumentText(doc.id)
  preview.value = { file_name: doc.file_name, text: data.text }
}
</script>

<template>
  <div class="page">
    <h1>Курс из документа</h1>
    <p class="subtitle">Шаг 1: загрузите документ, система достанет из него текст.</p>

    <UploadForm @uploaded="onUploaded" />

    <div v-if="notice" class="alert ok">{{ notice }}</div>
    <div v-if="loadError" class="alert error">{{ loadError }}</div>

    <DocumentList
      :documents="documents"
      @show-text="showText"
      @changed="refresh"
    />

    <div v-if="preview" class="card">
      <h2>Текст: {{ preview.file_name }}</h2>
      <pre class="text-preview">{{ preview.text }}</pre>
      <p class="hint">
        Это сырой текст из файла. На следующем шаге его разобьём на фрагменты
        и отправим языковой модели.
      </p>
    </div>
  </div>
</template>