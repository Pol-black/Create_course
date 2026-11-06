<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  addSection, deleteSection, exportUrl, getCourse, getVersions, regenerateSection,
  reorderSections, restoreVersion, updateCourse, updateSection,
} from '../api.js'
import { renderMarkdown } from '../markdown.js'
import SectionEditor from './SectionEditor.vue'
import VersionList from './VersionList.vue'

const props = defineProps({ courseId: { type: Number, required: true } })
const emit = defineEmits(['back', 'changed'])

const course = ref(null)
const selectedId = ref(null)
const mode = ref('read') // read | edit | versions | regenerate
const versions = ref([])
const busy = ref(false)
const error = ref('')
const notice = ref('')
const revealed = ref({})
const metaEdit = ref(null)
const hint = ref('')

const section = computed(() => course.value?.sections.find((s) => s.id === selectedId.value) || null)
const html = computed(() => renderMarkdown(section.value?.content.content_md))

async function call(action, { keep = false } = {}) {
  busy.value = true
  error.value = ''
  if (!keep) notice.value = ''
  try {
    return await action()
  } catch (e) {
    error.value = e.message
    return undefined
  } finally {
    busy.value = false
  }
}

async function load(selectId = selectedId.value) {
  const data = await call(() => getCourse(props.courseId), { keep: true })
  if (!data) return
  course.value = data
  const exists = data.sections.some((s) => s.id === selectId)
  selectedId.value = exists ? selectId : data.sections[0]?.id ?? null
}

onMounted(load)
watch(() => props.courseId, () => load(null))
watch(selectedId, () => {
  mode.value = 'read'
  revealed.value = {}
  error.value = ''
  notice.value = ''
})

function select(id) {
  selectedId.value = id
}

//правка раздела

async function saveSection(patch) {
  const result = await call(() => updateSection(section.value.id, patch))
  if (!result) return
  await load(section.value.id)
  mode.value = 'read'
  notice.value = 'Изменения сохранены новой версией раздела'
  emit('changed')
}

async function openVersions() {
  mode.value = 'versions'
  const list = await call(() => getVersions(section.value.id))
  if (list) versions.value = list
}

async function restore(version) {
  const result = await call(() => restoreVersion(section.value.id, version.id))
  if (!result) return
  await load(section.value.id)
  mode.value = 'read'
  notice.value = `Возвращена версия ${version.version_no}; она сохранена как новая`
}

async function regenerate() {
  const result = await call(() => regenerateSection(section.value.id, hint.value))
  if (!result) return
  hint.value = ''
  await load(section.value.id)
  mode.value = 'read'
  notice.value = 'Раздел сгенерирован заново; прежний вариант остался в истории версий'
}

// структура

async function move(index, delta) {
  const ids = course.value.sections.map((s) => s.id)
  const target = index + delta
  if (target < 0 || target >= ids.length) return
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  const result = await call(() => reorderSections(course.value.id, ids))
  if (result) course.value = result
}

async function addNew() {
  const title = prompt('Название нового раздела')
  if (!title || !title.trim()) return
  const result = await call(() => addSection(course.value.id, title.trim()))
  if (!result) return
  course.value = result
  selectedId.value = result.sections[result.sections.length - 1].id
  mode.value = 'edit'
}

async function removeSection() {
  if (!confirm(`Удалить раздел «${section.value.title}» вместе с историей версий?`)) return
  const ok = await call(() => deleteSection(section.value.id))
  if (ok === undefined && error.value) return
  await load(null)
  notice.value = 'Раздел удалён'
}

// свойства курса

function startMeta() {
  const c = course.value
  metaEdit.value = { title: c.title, description: c.description, goals: c.goals.join('\n') }
}

async function saveMeta() {
  const m = metaEdit.value
  if (!m.title.trim()) return (error.value = 'Название курса не может быть пустым')
  const result = await call(() =>
    updateCourse(course.value.id, {
      title: m.title.trim(),
      description: m.description,
      goals: m.goals.split('\n').map((g) => g.trim()).filter(Boolean),
    }),
  )
  if (!result) return
  course.value = result
  metaEdit.value = null
  notice.value = 'Описание курса сохранено'
  emit('changed')
}

const STATUS = { READY: 'готов', HAS_ISSUES: 'есть замечания', GENERATING: 'генерируется', FAILED: 'ошибка', PENDING: 'ожидает' }
const letter = (i) => String.fromCharCode(1040 + i) // А, Б, В…
</script>

<template>
  <div v-if="!course" class="card">
    <p v-if="error" class="alert error">{{ error }}</p>
    <p v-else class="hint">Загрузка курса…</p>
    <button @click="emit('back')">К списку курсов</button>
  </div>

  <div v-else>
    <div class="row">
      <button @click="emit('back')">← Все курсы</button>
      <a class="button-link" :href="exportUrl(course.id)">Скачать курс (Markdown)</a>
    </div>

    <div class="card course-head">
      <template v-if="!metaEdit">
        <div class="row">
          <h1>{{ course.title }}</h1>
          <button @click="startMeta">Изменить описание</button>
        </div>
        <p>{{ course.description }}</p>
        <div v-if="course.goals.length">
          <strong>Цели изучения</strong>
          <ul><li v-for="(g, i) in course.goals" :key="i">{{ g }}</li></ul>
        </div>
        <p v-if="course.document" class="hint">Источник: {{ course.document.file_name }}</p>
      </template>
      <form v-else class="editor" @submit.prevent="saveMeta">
        <label>Название курса<input v-model="metaEdit.title" type="text" /></label>
        <label>Описание<textarea v-model="metaEdit.description" rows="3"></textarea></label>
        <label>Цели изучения (по одной в строке)<textarea v-model="metaEdit.goals" rows="5"></textarea></label>
        <div class="row end">
          <button type="button" @click="metaEdit = null">Отмена</button>
          <button class="primary" type="submit" :disabled="busy">Сохранить</button>
        </div>
      </form>
    </div>

    <div v-if="notice" class="alert ok">{{ notice }}</div>
    <div v-if="error && mode !== 'edit'" class="alert error">{{ error }}</div>

    <div class="course-layout">
      <nav class="card sections">
        <h2>Разделы</h2>
        <ol>
          <li v-for="(s, i) in course.sections" :key="s.id" :class="{ active: s.id === selectedId }">
            <a href="#" @click.prevent="select(s.id)">{{ s.title }}</a>
            <span class="move">
              <button :disabled="busy || i === 0" title="Выше" @click="move(i, -1)">↑</button>
              <button :disabled="busy || i === course.sections.length - 1" title="Ниже" @click="move(i, 1)">↓</button>
            </span>
          </li>
        </ol>
        <button :disabled="busy" @click="addNew">Добавить раздел</button>
      </nav>

      <main v-if="section" class="card section-main">
        <div class="row">
          <h2>{{ section.title }}</h2>
          <span class="hint">
            версия {{ section.version_no }} из {{ section.versions_count }} · {{ STATUS[section.status] }}
          </span>
        </div>

        <div class="toolbar">
          <button :class="{ primary: mode === 'edit' }" :disabled="busy" @click="mode = 'edit'">Редактировать</button>
          <button :disabled="busy" @click="openVersions">История версий</button>
          <button :disabled="busy" @click="mode = 'regenerate'">Сгенерировать заново</button>
          <button v-if="mode !== 'read'" @click="mode = 'read'">Просмотр</button>
          <button class="danger" :disabled="busy" @click="removeSection">Удалить раздел</button>
        </div>

        <SectionEditor
          v-if="mode === 'edit'"
          :key="section.version_id"
          :content="section.content"
          :saving="busy"
          :error="error"
          @save="saveSection"
          @cancel="mode = 'read'"
        />

        <div v-else-if="mode === 'versions'">
          <VersionList :versions="versions" :busy="busy" @restore="restore" />
        </div>

        <div v-else-if="mode === 'regenerate'" class="regen">
          <p>
            Модель заново напишет только этот раздел по тем же фрагментам документа. Остальной курс не меняется,
            а текущий вариант останется в истории версий.
          </p>
          <label>Пожелание (необязательно)
            <textarea v-model="hint" rows="3" placeholder="Например: объясни проще и добавь больше примеров из документа"></textarea>
          </label>
          <button class="primary" :disabled="busy" @click="regenerate">{{ busy ? 'Генерируем…' : 'Сгенерировать' }}</button>
        </div>

        <template v-else>
          <p v-if="section.content.intro" class="intro">{{ section.content.intro }}</p>
          <p v-if="!section.content.content_md" class="hint">В разделе пока нет текста. Нажмите «Редактировать».</p>
          <div class="md" v-html="html"></div>

          <div v-if="section.content.terms.length" class="block">
            <h3>Термины</h3>
            <dl>
              <template v-for="t in section.content.terms" :key="t.term">
                <dt>{{ t.term }}</dt><dd>{{ t.definition }}</dd>
              </template>
            </dl>
          </div>

          <div v-if="section.content.summary.length" class="block">
            <h3>Выводы</h3>
            <ul><li v-for="(item, i) in section.content.summary" :key="i">{{ item }}</li></ul>
          </div>

          <div v-if="section.content.questions.length" class="block">
            <h3>Вопросы для самопроверки</h3>
            <div v-for="(q, i) in section.content.questions" :key="i" class="question">
              <p><strong>{{ i + 1 }}. {{ q.question }}</strong></p>
              <ul class="options">
                <li v-for="(o, j) in q.options" :key="j" :class="{ right: revealed[i] && j === q.correct_index }">
                  {{ letter(j) }}) {{ o }}
                </li>
              </ul>
              <button @click="revealed[i] = !revealed[i]">{{ revealed[i] ? 'Скрыть ответ' : 'Показать ответ' }}</button>
              <p v-if="revealed[i]" class="hint">{{ q.explanation }}</p>
            </div>
          </div>

          <div v-if="section.content.missing_info.length" class="alert warn">
            <strong>В документе не хватает данных:</strong>
            <ul><li v-for="(m, i) in section.content.missing_info" :key="i">{{ m }}</li></ul>
          </div>
        </template>
      </main>
    </div>
  </div>
</template>
