# AGENTS.md

## Назначение репозитория

`NexusCore` — интеграционный корень демонстрационной production-oriented мультитенантной SaaS-платформы для управления Telegram-ботами. Платформа объединяет существующие самостоятельные pet-проекты в одну систему; не переписывай сервисы с нуля без доказанной необходимости.

Ключевой пользовательский сценарий:

1. Пользователь регистрируется и проходит аутентификацию через AuthFortress.
2. Создаёт tenant/организацию и добавляет один или несколько Telegram-ботов.
3. Telegram отправляет update в WebHook Manager.
4. WebHook Manager аутентифицирует, дедуплицирует и ставит событие в очередь.
5. AgentHub выполняет RAG/cache/LLM routing, учитывает стоимость и формирует ответ.
6. Ответ доставляется в Telegram.
7. Метрики, логи, события и расходы становятся видны в dashboard/observability-контуре.

## Главный рабочий принцип

Двигайся маленькими проверяемыми шагами: **проверили → при необходимости починили → протестировали → зафиксировали результат → перешли дальше**.

- Не расширяй текущую задачу на следующий сервис или этап без явного запроса.
- Сначала изучай и проверяй уже реализованное. Не заменяй существующую реализацию только потому, что её ещё не проверяли.
- Не выдавай целевую архитектуру или roadmap за готовую функциональность.
- Любой статус `готово` должен опираться на воспроизводимую проверку, тест, HTTP-ответ, healthcheck или иной конкретный артефакт.
- Если документация расходится с кодом и фактическим запуском, источником истины являются код и воспроизводимое поведение; расхождение зафиксируй отдельно.

## Текущая точка работы

Текущий приоритет — **PHASE 1: AuthFortress**. По переданному контексту уже были проверены Docker, PostgreSQL, Redis, запуск приложения, Swagger и регистрация пользователя. Эти результаты считаются историческим контекстом и при необходимости должны быть перепроверены в текущем окружении.

Следующий незакрытый шаг:

```text
POST /api/v1/auth/login
        ↓
получить JWT
        ↓
вызвать защищённый endpoint
```

Не переходи к WebHook Manager, AgentHub, dashboard или observability, пока этот flow не подтверждён и пользователь явно не сменил приоритет.

Дальнейшая последовательность проверки AuthFortress:

1. Login → JWT → protected endpoint.
2. JWT sessions.
3. RBAC (`user`, `admin`, `superadmin`).
4. OAuth2: Google, GitHub, Yandex.
5. TOTP 2FA.
6. Rate limiting.
7. Prometheus metrics.
8. Dockerfile.

## Реальное состояние этого корня

На момент создания файла в репозитории находятся интеграционный `docker-compose.yml`, `.env.example` и SQL-инициализация баз. Git-история ещё не создана, remote отсутствует. Соседние сервисы подключаются как build contexts:

```text
../AuthFortress
../WebHook_Manager
../AgentHub
```

Не предполагай, что эти каталоги или их API неизменны: перед правками изучи соответствующий сервис, его README, OpenAPI, тесты и локальные инструкции (`AGENTS.md`, если есть).

Подтверждённые репозитории проекта:

| Подпроект | Локальный каталог | GitHub |
|---|---|---|
| AuthFortress | `../AuthFortress` | `https://github.com/sayomiyori/AuthFortress` |
| WebHook Manager | `../WebHook_Manager` | `https://github.com/sayomiyori/WebHook_Manager` |
| AgentHub | `../AgentHub` | `https://github.com/sayomiyori/AgentHub` |
| EventPipe | `../EventPipe` | `https://github.com/sayomiyori/EventPipe` |
| PipeWatch | `../PipeWatch` | `https://github.com/sayomiyori/PipeWatch` |

Это самостоятельные проекты и одновременно компоненты live demo-стенда NexusCore. Сохраняй возможность запускать и тестировать каждый репозиторий отдельно; корневая интеграция не должна незаметно превращать их в жёстко связанный монолит.

Текущая локальная инфраструктура:

| Компонент | Compose service | Контейнер | Host endpoint / порт |
|---|---|---|---|
| PostgreSQL + pgvector | `postgres` | `nexus-postgres` | `localhost:25432` |
| Redis | `redis` | `nexus-redis` | `localhost:26379` |
| AuthFortress | `auth_service` | `nexus-auth` | `http://localhost:28080` |
| WebHook Manager API | `webhook_service` | `nexus-webhook-api` | `http://localhost:8001` |
| WebHook worker | `webhook_worker` | `nexus-webhook-worker` | internal only |
| AgentHub API | `agent_service` | `nexus-agent-api` | `http://localhost:8014` |
| AgentHub worker | `agent_worker` | `nexus-agent-worker` | internal only |

Swagger AuthFortress ожидается по адресу `http://localhost:28080/docs`.

Внутри Compose-сети используй имена сервисов и container ports (`postgres:5432`, `redis:6379`, `auth_service:8000` и т. п.), а не `localhost`. Текущая сеть называется `nexus_net`. Не переименовывай её ради соответствия старому рабочему названию `bot-saas-network`, если это не отдельная согласованная миграция.

## Архитектурные границы

### AuthFortress

Единый identity layer: JWT, sessions, OAuth2, RBAC, TOTP 2FA, audit log, rate limiting и auth-метрики. Остальные сервисы не должны заводить собственную полноценную систему пользователей или независимо трактовать роли.

### WebHook Manager

Входной шлюз Telegram-событий: API-key/service authentication, идемпотентность, persistence, постановка в Celery, retry/delivery и передача в AgentHub. HTTP webhook не должен выполнять долгую LLM/RAG-работу синхронно.

### AgentHub

Общее AI-ядро для разных tenant'ов и ботов: multi-provider LLM routing, RAG/pgvector, semantic cache и cost tracking. Провайдер, модель, знания, cache keys и usage должны учитывать tenant и bot context.

### EventPipe / PipeWatch

Целевой observability-контур: сбор событий сервисов, ClickHouse, Redis Streams, WebSocket, Prometheus/Grafana и Telegram alerts. Это roadmap, пока конкретная интеграция не подтверждена кодом и тестами.

### Dashboard

Целевые разделы: Overview, Tenants, Bots, AI Configuration, Knowledge Base, Usage / Costs, Events, Observability. Dashboard должен объяснять архитектуру и состояние системы за 2–5 минут, но не является текущим этапом.

## Мультитенантные инварианты

Мультитенантность — обязательное свойство доменной модели, а не только поле в UI.

- Пользователь работает в контексте tenant/organization; tenant может владеть несколькими ботами.
- Bots, credentials, webhook settings, AI configuration, knowledge base, embeddings, cache, usage/costs, events и logs должны быть привязаны к tenant.
- Любая операция чтения, изменения, удаления, поиска и агрегации обязана ограничиваться авторизованным tenant context.
- Не доверяй `tenant_id` только из request body/query. Проверяй членство/роль через identity context.
- Сервисные события и задания очереди должны явно переносить `tenant_id`, `bot_id`, correlation/trace ID и idempotency key, где это применимо.
- Cache keys, vector search, метрики и аналитические запросы не должны смешивать данные tenant'ов.
- Тесты негативной изоляции обязательны: tenant A не может получить или изменить данные tenant B даже при знании идентификатора.

## Контракты и интеграция

- Сохраняй независимость сервисов и общайся через явные HTTP/event contracts.
- Не импортируй Python-модули напрямую из соседнего микросервиса как способ интеграции.
- Изменение межсервисного payload/API требует обратной совместимости либо согласованного обновления producer, consumer и тестов.
- Для событий предпочитай стабильный envelope: `event_id`, `event_type`, `schema_version`, `occurred_at`, `tenant_id`, `bot_id`, `correlation_id`, `payload`.
- Consumer должен быть идемпотентным; retry не должен создавать повторный ответ, расход или событие.
- Таймауты, ограниченные retry с backoff и различие transient/permanent errors должны быть явными.
- Секреты и Telegram/LLM credentials не передавай в логах и пользовательских ошибках.

## Безопасность и конфигурация

- Никогда не коммить `.env`, реальные JWT/OAuth/API/TOTP/Telegram/LLM ключи, пароли или токены. Обновляй только `.env.example` безопасными заглушками.
- Не выводи секреты в terminal output, логи, фикстуры, README и ответы об ошибках.
- Не ослабляй auth, RBAC, tenant filtering или TLS-предпосылки ради прохождения теста.
- Храни bot/LLM credentials зашифрованно или через secret storage, когда соответствующий этап будет реализован.
- Проверяй срок жизни и тип JWT, session state/revocation и права субъекта на защищённом endpoint.
- Публичный Telegram webhook должен проверять предусмотренный secret/API-key механизм и валидировать входные данные.
- Сохраняй audit trail для чувствительных auth/admin-операций, не включая в него секреты.

## Порядок работы агента

1. Прочитай задачу и определи один текущий микрошаг.
2. Проверь `git status` во всех затрагиваемых репозиториях; не перезаписывай пользовательские изменения.
3. Изучи реализацию, конфигурацию, миграции и тесты до внесения правок.
4. Воспроизведи проблему или зафиксируй baseline.
5. Сделай минимальное изменение в правильном сервисе.
6. Запусти сначала узкие тесты, затем релевантный набор интеграционных проверок.
7. Для Compose-проверки используй health/status/logs и реальный API flow.
8. Сообщи: что доказано, что изменено, чем проверено, что осталось неподтверждённым.

Не делай широкие рефакторинги, переименования, обновления зависимостей или форматирование несвязанных файлов в рамках узкой проверки.

## Проверки и Definition of Done

Выбирай команды по документации конкретного сервиса; не придумывай их при наличии Makefile/pyproject/README/CI. Для корневого Compose полезны:

```powershell
docker compose config
docker compose up -d
docker compose ps
docker compose logs --tail 200 <service>
```

Перед `up` сначала запускай `docker compose config`: текущие URL/переменные окружения необходимо проверить на корректную Compose-интерполяцию, не раскрывая значения `.env`.

Микрошаг считается завершённым, когда одновременно выполнены применимые пункты:

- конфигурация валидна;
- нужные контейнеры healthy/running;
- миграции применяются воспроизводимо;
- happy path проверен;
- ключевой отказ/запрет проверен (например, invalid credentials или cross-tenant access);
- автоматические тесты проходят;
- в логах нет необъяснённых traceback/retry loop;
- документация и `.env.example` обновлены, если изменился публичный контракт или конфигурация.

Для текущего auth-шага минимальное доказательство: успешный login, получение JWT без публикации токена, успешный вызов защищённого endpoint с ним и отклонение вызова без/с неверным токеном.

## Целевая архитектура и roadmap

Итоговый локальный/production контур планирует включать PostgreSQL/pgvector, Redis, AuthFortress, WebHook Manager, AgentHub, EventPipe/PipeWatch, dashboard, ClickHouse, Prometheus и Grafana; на VPS — Nginx, HTTPS/SSL, CI/CD, backup и monitoring.

Целевой observability-набор:

- Prometheus: request count, latency, errors, queue depth/processing, health и ресурсы.
- Grafana: health, throughput, latency, errors и рабочие dashboards.
- ClickHouse: объёмные события/логи и историческая аналитика.
- Redis Streams/WebSocket: поток и real-time представление событий.
- Telegram alerts: только actionable/critical события с защитой от alert storms.

Не добавляй все эти компоненты одновременно. Подключай следующий только после закрытия текущего этапа и с отдельной проверкой.

## Документация и статусы

- Разделяй `Implemented`, `Verified`, `Planned` и `Blocked/Unknown`.
- Не придумывай GitHub URL, live demo, домен, показатели uptime/cost или результаты тестов.
- Используй только подтверждённые URL из таблицы репозиториев выше. `https://github.com/sayomiyori/VeloxRAG` — отдельный известный проект; не приписывай его AgentHub.
- Корневой README должен быть короткой презентацией: архитектура, возможности, сервисы, стек, demo, local development, production, ADR/решения и roadmap.
- Комментарии к коду объясняют причины и инварианты, а не повторяют синтаксис.
- Новые имена, API и документацию пиши последовательно; технические идентификаторы и код — на английском.

## Git и область изменений

- Репозиторий может быть грязным; сохраняй все несвязанные изменения пользователя.
- Не используй destructive Git-команды и не удаляй volumes/данные без прямого запроса.
- Не создавай commit, branch, tag или PR без явного запроса.
- Постоянное разрешение пользователя: пушь коммиты, созданные в рамках текущей задачи, как только релевантные тесты и проверки успешно пройдены и нет известных регрессий. Если проверки не прошли, не запускались или результат неоднозначен — не пушь до устранения проблемы и повторной проверки.
- Это разрешение не распространяется на чужие или ранее существовавшие локальные коммиты, незавершённые изменения и секреты; перед push проверь состав коммитов, целевую ветку, remote и состояние рабочего дерева.
- При изменениях в соседнем сервисе явно перечисли, какой репозиторий и какие файлы затронуты.
- Если для задачи нужен отсутствующий репозиторий, credential, OAuth application, Telegram token, LLM key, домен или VPS-доступ, остановись на проверяемой локальной границе и точно опиши блокер.
