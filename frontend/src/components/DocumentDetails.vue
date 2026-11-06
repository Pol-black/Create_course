<script setup>
import { ref, watch } from 'vue'
import { getChunks, getDocumentText, getLog } from '../api.js'

const props = defineProps({
  doc: { type: Object, required: true },
  tab: { type: String, default: 'text' },
  version: { type: Number, default: 0 }, // меняется, когда документ обновился
})

const current = ref(props.tab)
const text = ref('')
const chunks = ref([])
const log = ref([])
const error = ref('')

async function load() {
  error.value = ''
  try {
    if (current.value === 'text') text.value = props.doc.text_length ? (await getDocumentText(props.doc.id)).text : ''
    else if (current.value === 'chunks') chunks.value = await getChunks(props.doc.id)
    else log.value = await getLog(props.doc.id)
  } catch (e) {
    error.value = e.message
  }
}

watch(() => props.tab, (t) => { current.value = t })
watch(() => [props.doc.id, props.version, current.value], load, { immediate: true })

function pages(c) {
  if (!c.page_from) return ''
  return c.page_from === c.page_to ? `стр. ${c.page_from}` : `стр. ${c.page_from}–${c.page_to}`
}
</script>

<template>
  <div class="card">
    <h2>{{ doc.file_name }}</h2>
    <div class="tabs">
      <button :class="{ active: current === 'text' }" @click="current = 'text'">Текст</button>
      <button :class="{ active: current === 'chunks' }" @click="current = 'chunks'">Фрагменты</button>
      <button :class="{ active: current === 'log' }" @click="current = 'log'">Журнал</button>
    </div>

    <div v-if="error" class="alert error">{{ error }}</div>

    <template v-if="current === 'text'">
      <p v-if="!text" class="hint">Текст появится после обработки.</p>
      <pre v-else class="text-preview">{{ text }}</pre>
    </template>

    <template v-else-if="current === 'chunks'">
      <p v-if="!chunks.length" class="hint">Фрагментов пока нет.</p>
      <div v-for="c in chunks" :key="c.id" class="chunk">
        <div class="chunk-head">
          <strong>№{{ c.position }}. {{ c.heading || 'Без заголовка' }}</strong>
          <span class="hint">{{ pages(c) }} · {{ c.words }} слов</span>
        </div>
        <pre class="text-preview">{{ c.text }}</pre>
      </div>
    </template>

    <template v-else>
      <p v-if="!log.length" class="hint">Записей нет.</p>
      <table v-else>
        <tbody>
          <tr v-for="r in log" :key="r.id">
            <td>{{ new Date(r.created_at).toLocaleTimeString('ru-RU') }}</td>
            <td>{{ r.stage }}</td>
            <td>{{ r.level }}</td>
            <td>{{ r.message }}<span v-if="r.duration_ms != null" class="hint"> ({{ r.duration_ms }} мс)</span></td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
