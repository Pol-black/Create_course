<script setup>
import { createDraftCourse, deleteDocument, processDocument } from '../api.js'

const props = defineProps({
  documents: { type: Array, required: true },
  courses: { type: Array, default: () => [] },
})
const emit = defineEmits(['show', 'changed', 'error', 'open-course'])

const STATUS_LABELS = {
  UPLOADED: 'Загружен',
  PROCESSING: 'Обработка',
  PROCESSED: 'Обработан',
  FAILED: 'Ошибка',
}

function sizeKb(bytes) {
  return bytes ? `${Math.round(bytes / 1024)} КБ` : '—'
}

function when(iso) {
  return new Date(iso).toLocaleString('ru-RU')
}

function processLabel(doc) {
  if (doc.status === 'FAILED') return 'Повторить'
  if (doc.status === 'PROCESSED') return 'Обработать заново'
  return 'Обработать'
}

async function run(action) {
  try {
    await action()
  } catch (e) {
    emit('error', e.message)
  }
  emit('changed')
}

function process(doc) {
  return run(() => processDocument(doc.id))
}

const courseOf = (doc) => props.courses.find((c) => c.document_id === doc.id)

async function makeCourse(doc) {
  const existing = courseOf(doc)
  if (existing && !confirm('Для этого документа курс уже есть. Заменить его новым черновиком? Правки и версии прежнего курса будут удалены.')) return
  try {
    const course = await createDraftCourse(doc.id, Boolean(existing))
    emit('changed')
    emit('open-course', course.id)
  } catch (e) {
    emit('error', e.message)
  }
}

function remove(doc) {
  if (!confirm(`Удалить «${doc.file_name}»?`)) return
  return run(() => deleteDocument(doc.id))
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
          <th>Фрагментов</th>
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
          <td>{{ doc.chunks_count || '—' }}</td>
          <td>{{ when(doc.created_at) }}</td>
          <td class="actions">
            <button
              class="primary"
              :disabled="doc.status === 'PROCESSING'"
              @click="process(doc)"
            >{{ doc.status === 'PROCESSING' ? 'Обработка…' : processLabel(doc) }}</button>
            <button v-if="courseOf(doc)" @click="emit('open-course', courseOf(doc).id)">Открыть курс</button>
            <button v-if="doc.status === 'PROCESSED' && doc.chunks_count" @click="makeCourse(doc)">
              {{ courseOf(doc) ? 'Пересоздать курс' : 'Создать курс' }}
            </button>
            <button @click="emit('show', doc, 'text')" v-if="doc.text_length">Текст</button>
            <button @click="emit('show', doc, 'chunks')" v-if="doc.chunks_count">Фрагменты</button>
            <button @click="emit('show', doc, 'log')">Журнал</button>
            <button :disabled="doc.status === 'PROCESSING'" @click="remove(doc)">Удалить</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>