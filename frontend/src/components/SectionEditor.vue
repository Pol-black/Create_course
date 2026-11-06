<script setup>
import { computed, ref } from 'vue'
import { renderMarkdown } from '../markdown.js'

const props = defineProps({
  content: { type: Object, required: true },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['save', 'cancel'])

const lines = (items) => (items || []).join('\n')
const split = (text) => text.split('\n').map((s) => s.trim()).filter(Boolean)

const form = ref({
  title: props.content.title,
  intro: props.content.intro || '',
  content_md: props.content.content_md || '',
  summary: lines(props.content.summary),
  missing_info: lines(props.content.missing_info),
  terms: (props.content.terms || []).map((t) => ({ ...t })),
  questions: (props.content.questions || []).map((q) => ({
    question: q.question,
    options: lines(q.options),
    correct: q.correct_index + 1, // в форме нумерация с 1
    explanation: q.explanation,
  })),
})
const preview = ref(true)
const localError = ref('')
const html = computed(() => renderMarkdown(form.value.content_md))

const addTerm = () => form.value.terms.push({ term: '', definition: '' })
const addQuestion = () =>
  form.value.questions.push({ question: '', options: '', correct: 1, explanation: '' })

function save() {
  localError.value = ''
  const f = form.value
  if (!f.title.trim()) return (localError.value = 'Название раздела не может быть пустым')

  const terms = f.terms.filter((t) => t.term.trim() || t.definition.trim())
  if (terms.some((t) => !t.term.trim() || !t.definition.trim())) {
    return (localError.value = 'У каждого термина должны быть и название, и определение')
  }

  const questions = f.questions.filter((q) => q.question.trim() || q.options.trim())
  for (const [i, q] of questions.entries()) {
    const options = split(q.options)
    if (!q.question.trim()) return (localError.value = `Вопрос ${i + 1}: введите текст вопроса`)
    if (options.length < 2) return (localError.value = `Вопрос ${i + 1}: нужно хотя бы два варианта ответа (каждый с новой строки)`)
    if (!(q.correct >= 1 && q.correct <= options.length)) {
      return (localError.value = `Вопрос ${i + 1}: номер правильного ответа должен быть от 1 до ${options.length}`)
    }
    if (!q.explanation.trim()) return (localError.value = `Вопрос ${i + 1}: добавьте пояснение к ответу`)
  }

  emit('save', {
    title: f.title.trim(),
    intro: f.intro.trim(),
    content_md: f.content_md,
    summary: split(f.summary),
    missing_info: split(f.missing_info),
    terms: terms.map((t) => ({ term: t.term.trim(), definition: t.definition.trim() })),
    questions: questions.map((q) => ({
      question: q.question.trim(),
      options: split(q.options),
      correct_index: Number(q.correct) - 1,
      explanation: q.explanation.trim(),
    })),
  })
}
</script>

<template>
  <form class="editor" @submit.prevent="save">
    <label>Название раздела
      <input v-model="form.title" type="text" />
    </label>

    <label>Коротко о разделе
      <textarea v-model="form.intro" rows="2"></textarea>
    </label>

    <div class="row">
      <strong>Текст раздела (Markdown)</strong>
      <label class="inline"><input v-model="preview" type="checkbox" /> предпросмотр</label>
    </div>
    <div class="split" :class="{ single: !preview }">
      <textarea v-model="form.content_md" rows="22" class="mono" spellcheck="false"></textarea>
      <div v-if="preview" class="md preview" v-html="html"></div>
    </div>

    <fieldset>
      <legend>Термины</legend>
      <div v-for="(t, i) in form.terms" :key="i" class="term-row">
        <input v-model="t.term" type="text" placeholder="Термин" />
        <input v-model="t.definition" type="text" placeholder="Определение" />
        <button type="button" @click="form.terms.splice(i, 1)">Убрать</button>
      </div>
      <button type="button" @click="addTerm">Добавить термин</button>
    </fieldset>

    <label>Выводы (по одному в строке)
      <textarea v-model="form.summary" rows="4"></textarea>
    </label>

    <fieldset>
      <legend>Вопросы для самопроверки</legend>
      <div v-for="(q, i) in form.questions" :key="i" class="question-edit">
        <input v-model="q.question" type="text" placeholder="Вопрос" />
        <textarea v-model="q.options" rows="3" placeholder="Варианты ответа, каждый с новой строки"></textarea>
        <div class="row">
          <label class="inline">Номер правильного ответа
            <input v-model.number="q.correct" type="number" min="1" class="narrow" />
          </label>
        </div>
        <input v-model="q.explanation" type="text" placeholder="Пояснение к ответу" />
        <button type="button" @click="form.questions.splice(i, 1)">Убрать вопрос</button>
      </div>
      <button type="button" @click="addQuestion">Добавить вопрос</button>
    </fieldset>

    <label>Чего не хватает в документе (по одному в строке)
      <textarea v-model="form.missing_info" rows="2"></textarea>
    </label>

    <div v-if="localError || error" class="alert error">{{ localError || error }}</div>

    <div class="row end">
      <button type="button" :disabled="saving" @click="emit('cancel')">Отмена</button>
      <button type="submit" class="primary" :disabled="saving">{{ saving ? 'Сохраняем…' : 'Сохранить как новую версию' }}</button>
    </div>
  </form>
</template>
