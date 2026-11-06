<script setup>
import { ref } from 'vue'
import { renderMarkdown } from '../markdown.js'

defineProps({ versions: { type: Array, required: true }, busy: { type: Boolean, default: false } })
const emit = defineEmits(['restore'])

const open = ref(null)
const AUTHORS = { AI: 'модель', USER: 'пользователь' }
const when = (iso) => new Date(iso).toLocaleString('ru-RU')

function describe(v) {
  if (v.prompt_name && v.prompt_name.startsWith('restore:')) return `возврат к версии ${v.prompt_name.slice(9)}`
  if (v.model === 'example') return 'пример курса'
  if (v.model === 'draft') return 'черновик по правилам'
  if (v.author === 'AI') return `модель ${v.model || ''}`.trim()
  return 'правка вручную'
}
</script>

<template>
  <div>
    <p class="hint">Правка или повторная генерация не затирают прежний текст: каждая сохраняется отдельной версией.</p>
    <div v-for="v in versions" :key="v.id" class="version" :class="{ current: v.is_current }">
      <div class="row">
        <div>
          <strong>Версия {{ v.version_no }}</strong>
          <span v-if="v.is_current" class="status PROCESSED">текущая</span>
          <div class="hint">
            {{ AUTHORS[v.author] }} · {{ describe(v) }} · {{ when(v.created_at) }}
            <span v-if="v.user_hint"> · пожелание: «{{ v.user_hint }}»</span>
          </div>
        </div>
        <div class="actions">
          <button @click="open = open === v.id ? null : v.id">{{ open === v.id ? 'Скрыть' : 'Показать' }}</button>
          <button v-if="!v.is_current" :disabled="busy" @click="emit('restore', v)">Вернуть эту версию</button>
        </div>
      </div>
      <div v-if="open === v.id" class="md version-body" v-html="renderMarkdown(v.content.content_md)"></div>
    </div>
  </div>
</template>
