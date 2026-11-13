<script setup>
const projects = [
  {
    id: 1,
    name: 'Для ИИ',
    datasets: ['Клиенты', 'Заказы'],
  },
  {
    id: 2,
    name: 'Каталог магазина',
    datasets: ['Товары'],
  },
  {
    id: 3,
    name: 'Новый проект',
    datasets: [],
  },
]
</script>

<template>
  <section class="project-list">
    <p class="project-list__title">Проекты</p>

    <article
      v-for="project in projects"
      :key="project.id"
      class="project-item"
    >
      <button class="project-item__name" type="button">
        {{ project.name }}
      </button>

      <div class="project-item__datasets">
        <button
          v-for="dataset in project.datasets"
          :key="dataset"
          class="dataset-item"
          type="button"
        >
          {{ dataset }}
        </button>

        <button class="dataset-add" type="button">
          + Добавить датасет
        </button>
      </div>
    </article>

    <button class="project-add" type="button">
      + Добавить проект
    </button>
  </section>
</template>