<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import UploadForm from './components/UploadForm.vue'
import DocumentList from './components/DocumentList.vue'
import DocumentDetails from './components/DocumentDetails.vue'
import CourseList from './components/CourseList.vue'
import CourseView from './components/CourseView.vue'
import { listCourses, listDocuments } from './api.js'

const documents = ref([])
const courses = ref([])
const loadError = ref('')
const notice = ref('')
const selected = ref({ id: null, tab: 'text' })
const version = ref(0)
const view = ref('documents') // documents | courses | course
const courseId = ref(null)
let timer = null

const selectedDoc = computed(() => documents.value.find((d) => d.id === selected.value.id) || null)

async function refresh() {
  try {
    ;[documents.value, courses.value] = await Promise.all([listDocuments(), listCourses()])
    loadError.value = ''
    version.value++
  } catch (e) {
    loadError.value = `Не удалось получить данные: ${e.message}`
  }
}

// Пока документ обрабатывается, опрашиваем сервер
onMounted(() => {
  readHash()
  window.addEventListener('hashchange', readHash)
  refresh()
  timer = setInterval(() => {
    if (documents.value.some((d) => d.status === 'PROCESSING')) refresh()
  }, 2000)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  window.removeEventListener('hashchange', readHash)
})

function readHash() {
  const match = /^#\/courses\/(\d+)$/.exec(location.hash)
  if (match) {
    courseId.value = Number(match[1])
    view.value = 'course'
  } else if (location.hash === '#/courses') {
    view.value = 'courses'
  } else {
    view.value = 'documents'
  }
}

function go(target) {
  location.hash = target === 'documents' ? '#/' : '#/courses'
}

function openCourse(id) {
  location.hash = `#/courses/${id}`
}

async function onUploaded(doc) {
  notice.value = `Файл «${doc.file_name}» загружен. Нажмите «Обработать», чтобы извлечь текст и разбить его на фрагменты.`
  await refresh()
}

function show(doc, tab) {
  selected.value = { id: doc.id, tab }
}
</script>

<template>
  <div class="page" :class="{ wide: view === 'course' }">
    <header class="top">
      <h1>Курс из документа</h1>
      <nav class="nav">
        <a href="#/" :class="{ active: view === 'documents' }" @click.prevent="go('documents')">Документы</a>
        <a href="#/courses" :class="{ active: view !== 'documents' }" @click.prevent="go('courses')">Курсы</a>
      </nav>
    </header>

    <div v-if="loadError" class="alert error">{{ loadError }}</div>

    <template v-if="view === 'documents'">
      <p class="subtitle">
        Загрузите документ и нажмите «Обработать»: система извлечёт текст, очистит его и разобьёт на фрагменты.
      </p>
      <UploadForm @uploaded="onUploaded" />
      <div v-if="notice" class="alert ok">{{ notice }}</div>

      <DocumentList
        :documents="documents"
        :courses="courses"
        @show="show"
        @changed="refresh"
        @error="(m) => (loadError = m)"
        @open-course="openCourse"
      />
      <DocumentDetails v-if="selectedDoc" :doc="selectedDoc" :tab="selected.tab" :version="version" />
    </template>

    <CourseList v-else-if="view === 'courses'" :courses="courses" @open="openCourse" @changed="refresh" />

    <CourseView v-else :course-id="courseId" @back="go('courses')" @changed="refresh" />
  </div>
</template>
