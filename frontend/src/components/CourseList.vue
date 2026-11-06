<script setup>
import { ref } from 'vue'
import { createExampleCourse, deleteCourse } from '../api.js'

defineProps({ courses: { type: Array, required: true } })
const emit = defineEmits(['open', 'changed'])

const busy = ref(false)
const error = ref('')

async function run(action) {
  busy.value = true
  error.value = ''
  try {
    return await action()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function createExample() {
  const course = await run(createExampleCourse)
  emit('changed')
  if (course) emit('open', course.id)
}

async function remove(course) {
  if (!confirm(`Удалить курс «${course.title}» со всеми разделами и версиями?`)) return
  await run(() => deleteCourse(course.id))
  emit('changed')
}

const when = (iso) => new Date(iso).toLocaleString('ru-RU')
</script>

<template>
  <div class="card">
    <div class="row">
      <h2>Курсы</h2>
      <button class="primary" :disabled="busy" @click="createExample">
        {{ busy ? 'Создаём…' : 'Создать пример курса' }}
      </button>
    </div>
    <p class="hint">
      Пример — готовый курс по документу MPI.pdf: на нём можно проверить просмотр, редактирование, порядок разделов и версии.
      Курс по своему документу создаётся кнопкой «Создать курс» на вкладке «Документы».
    </p>

    <div v-if="error" class="alert error">{{ error }}</div>
    <p v-if="!courses.length" class="hint">Курсов пока нет.</p>

    <table v-else>
      <thead>
        <tr><th>Курс</th><th>Документ</th><th>Разделов</th><th>Изменён</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="c in courses" :key="c.id">
          <td><a href="#" @click.prevent="emit('open', c.id)">{{ c.title }}</a></td>
          <td>{{ c.document_name }}</td>
          <td>{{ c.sections_count }}</td>
          <td>{{ when(c.updated_at) }}</td>
          <td class="actions">
            <button class="primary" @click="emit('open', c.id)">Открыть</button>
            <button :disabled="busy" @click="remove(c)">Удалить</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
