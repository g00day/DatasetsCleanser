# DatasetCleanser

Vue-приложение для работы с проектами, загрузки CSV и очистки версий датасетов.

## Локальный запуск

```powershell
npm.cmd ci
npm.cmd run dev
```

Для локальной разработки запустите Django из ветки `backend/dev` на
`127.0.0.1:8000` и откройте Vue через `http://localhost:5173`.
Vite проксирует `/api/v1` в Django, сохраняя Host для проверки Origin.
Адрес назначения можно изменить через `API_PROXY_TARGET` в `.env.local`.
Для обработки CSV, проверки и очистки отдельно запустите `python manage.py run_jobs`.
В production направьте `/api/v1` в Django через прокси хостинга. Для отдельного сервера
скопируйте `.env.example` в `.env.local`, задайте полный `VITE_API_BASE_URL`
и перезапустите Vite. Сборка для публикации — `npm.cmd run build`.
На хостинге маршруты интерфейса должны возвращать `index.html`.

## Docker

Соберите образ из корня frontend-репозитория:

```powershell
docker build -t datasetcleanser-frontend .
```

Для Django в Docker запустите фронтенд в той же пользовательской сети. В примере
сеть называется `datasetcleanser`, а контейнер Django доступен в ней как `backend:8000`.
Подставьте имя своей сети и адрес сервиса:

```powershell
docker run --rm --network datasetcleanser -p 8080:80 -e BACKEND_URL=http://backend:8000 datasetcleanser-frontend
```

Для Django на компьютере с Docker Desktop:

```powershell
docker network create datasetcleanser
docker run --rm --network datasetcleanser -p 8080:80 -e BACKEND_URL=http://host.docker.internal:8000 datasetcleanser-frontend
```

Создание сети требуется один раз. Откройте `http://localhost:8080`.
Nginx отдаёт Vue и проксирует запросы `/api/v1/` с сохранением пути и заголовка Host.
В `BACKEND_URL` указывайте схему, имя хоста и порт без пути и завершающего слеша.
Адрес можно сменить при запуске контейнера. Для ссылок восстановления пароля задайте
в Django `FRONTEND_URL=http://localhost:8080`.

## Подключение API

Все пути находятся в `src/api/endpoints.js`. Шаблон `:id` подставляет идентификатор
проекта, датасета, версии или задания согласно операции. Формы и страницы используют
имена операций. Формат запросов и ответов соответствует контракту BACKEND_SPEC.md
в рабочей папке проекта. При изменении схемы ответа понадобится адаптация данных.

Клиент передаёт cookie с запросами, получает CSRF-токен перед изменениями и отправляет
его в заголовке `X-CSRFToken`. Для отдельного origin на сервере требуются CORS
с адресом фронтенда, поддержка credentials и разрешение используемых заголовков.
Загрузка файла, проверка и очистка используют `Idempotency-Key` и ожидают
результат через эндпоинт заданий. Для входа и данных рабочего пространства нужен API.
