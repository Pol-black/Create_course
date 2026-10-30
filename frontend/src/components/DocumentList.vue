<script setup>
import { deleteDocument } from '../api.js'

const props = defineProps({
  documents: { type: Array, required: true },
})
const emit = defineEmits(['show-text', 'changed'])

const STATUS_LABELS = {
  UPLOADED: 'Загружен',
  PROCESSING: 'Обработка',
  PROCESSED: 'Текст извлечён',
  FAILED: 'Ошибка',
}

function sizeKb(bytes) {
  return bytes ? `${Math.round(bytes / 1024)} КБ` : '—'
}

function when(iso) {
  return new Date(iso).toLocaleString('ru-RU')
}

async function remove(doc) {
  if (!confirm(`Удалить «${doc.file_name}»?`)) return
  await deleteDocument(doc.id)
  emit('changed')
}
</script>

<template>
  <div class="card">
    <h2>Загруженные документы</h2>

    <p v-if="!props.documents.length" class="hint">Пока ничего не загружено.</p>

    <table v-else>
      <thead>
        <tr>
          <th>Файл</th>
          <th>Размер</th>
          <th>Статус</th>
          <th>Символов</th>
          <th>Когда</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <!-- :key нужен Vue, чтобы не перерисовывать всю таблицу при изменении одной строки -->
        <tr v-for="doc in props.documents" :key="doc.id">
          <td>
            {{ doc.file_name }}
            <div v-if="doc.error_message" class="hint">{{ doc.error_message }}</div>
          </td>
          <td>{{ sizeKb(doc.file_size) }}</td>
          <td><span class="status" :class="doc.status">{{ STATUS_LABELS[doc.status] }}</span></td>
          <td>{{ doc.text_length || '—' }}</td>
          <td>{{ when(doc.created_at) }}</td>
          <td>
            <button
              v-if="doc.status === 'PROCESSED'"
              @click="emit('show-text', doc)"
            >Текст</button>
            <button @click="remove(doc)">Удалить</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>