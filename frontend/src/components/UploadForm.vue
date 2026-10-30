<script setup>

import { ref } from 'vue'
import { uploadDocument } from '../api.js'


const emit = defineEmits(['uploaded'])

const busy = ref(false)        
const error = ref('')          
const dragOver = ref(false)    
const fileInput = ref(null)    

const ALLOWED = ['.pdf', '.docx', '.txt']

function pickFile() {
  fileInput.value.click()
}

async function send(file) {
  if (!file) return

  const dot = file.name.lastIndexOf('.')
  const ext = dot === -1 ? '' : file.name.slice(dot).toLowerCase()
  if (!ALLOWED.includes(ext)) {
    error.value = `Можно загрузить только ${ALLOWED.join(', ')}`
    return
  }

  busy.value = true
  error.value = ''
  try {
    const doc = await uploadDocument(file)
    emit('uploaded', doc)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onDrop(event) {
  dragOver.value = false
  if (busy.value) return
  send(event.dataTransfer.files[0])
}
</script>

<template>
  <div class="card">
    <h2>Загрузить документ</h2>

    <div
      class="dropzone"
      :class="{ over: dragOver, busy }"
      @click="pickFile"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <template v-if="busy">
        <strong>Обрабатываем файл…</strong>
        <p class="hint">Читаем документ и достаём из него текст</p>
      </template>
      <template v-else>
        <strong>Перетащите файл сюда или нажмите, чтобы выбрать</strong>
        <p class="hint">PDF, DOCX или TXT, до 25 МБ. Нужен текстовый документ, не скан.</p>
      </template>
    </div>

    <input
      ref="fileInput"
      type="file"
      accept=".pdf,.docx,.txt"
      hidden
      @change="send($event.target.files[0])"
    />

    <div v-if="error" class="alert error">{{ error }}</div>
  </div>
</template>