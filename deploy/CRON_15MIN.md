# Скан каждые 15 минут (компьютер выключен)

Встроенный cron GitHub **ненадёжен** — бывают паузы по 3–4 часа.  
Чтобы сигналы приходили **ровно каждые 15 минут**, нужен **бесплатный внешний таймер**
[cron-job.org](https://cron-job.org) — он «будит» GitHub по API.

> **Один раз настроил — работает 24/7 без твоего ПК.**

---

## Шаг 1. Токен GitHub (Personal Access Token)

1. Открой: https://github.com/settings/tokens  
2. **Generate new token** → **Generate new token (classic)**  
3. Название: `cron-scan`  
4. Срок: **No expiration** *(или 90 days — потом обновишь)*  
5. Галочка: **`repo`** (полный доступ к репозиториям)  
6. **Generate token** → **скопируй** (показывается один раз!)  
   Пример: `ghp_xxxxxxxxxxxxxxxxxxxx`

---

## Шаг 2. Аккаунт на cron-job.org

1. https://cron-job.org/en/signup/ — регистрация (бесплатно, без карты)  
2. Подтверди почту  

---

## Шаг 3. Создать задачу (cron job)

1. Войди → **Cronjobs** → **Create cronjob**  

2. **Title:** `crypto-signals scan`

3. **URL:**
   ```
   https://api.github.com/repos/VB737373/Cursor/dispatches
   ```

4. **Schedule:** каждые 15 минут  
   - Режим **Every 15 minutes**  
   - или вручную: `*/15 * * * *`

5. **Request method:** `POST`

6. **Headers** (добавь три строки):

   | Header | Value |
   |--------|--------|
   | `Authorization` | `Bearer ghp_ТВОЙ_ТОКЕН` |
   | `Accept` | `application/vnd.github+json` |
   | `X-GitHub-Api-Version` | `2022-11-28` |

7. **Request body** (тип JSON или Raw):

   ```json
   {"event_type":"scan"}
   ```

8. **Notifications:** можно включить email при ошибке  

9. **Create** / **Save**

---

## Шаг 4. Проверка

1. В cron-job.org нажми **Run now** (тестовый запуск)  
2. Через 1–2 мин открой:  
   https://github.com/VB737373/Cursor/actions/workflows/signals.yml  
3. Должен появиться новый run с событием **`repository_dispatch`**  
4. Если есть подходящие монеты — придут сигналы в Telegram  

---

## Как это работает

```
cron-job.org (каждые 15 мин)
       ↓ POST /dispatches
GitHub Actions → scan_ci.py → Telegram
```

Резервный запуск **раз в час** остаётся во встроенном cron GitHub — на случай,
если cron-job.org временно недоступен.

---

## Безопасность

- Токен `ghp_...` хранится **только** на cron-job.org — **не** коммить в GitHub  
- Достаточно прав **`repo`** только для твоего репозитория  
- Если токен утёк — удали на GitHub и создай новый  

---

## Частые проблемы

| Проблема | Решение |
|----------|---------|
| HTTP 401 | Неверный или просроченный токен |
| HTTP 404 | Проверь URL репозитория |
| Run не появляется | В Actions включи workflow (I understand… enable) |
| Скан есть, сигналов нет | Нормально — нет монет ≥69% или cooldown 15 мин |

---

## Поменять интервал

В cron-job.org измени расписание, например **Every 10 minutes**.  
В `.env.ci` при желании подстрой `COOLDOWN_MINUTES` под тот же интервал.
