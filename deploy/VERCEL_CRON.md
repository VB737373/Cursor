# Надёжный cron каждые 15 мин (Vercel, бесплатно)

GitHub сам часто пропускает расписание. **Vercel Cron** будит скан точно каждые 15 минут.

## Быстрая установка (5 мин, один раз)

### 1. Токен GitHub
https://github.com/settings/tokens → **Generate new token (classic)** → галочка **`repo`** → скопируй `ghp_...`

### 2. Деплой на Vercel
1. https://vercel.com/signup (можно через GitHub)
2. **Add New Project** → Import `VB737373/Cursor`
3. **Root Directory:** `cron`  ← важно!
4. **Environment Variables:**
   - `GITHUB_PAT` = твой `ghp_...`
   - `GITHUB_REPO` = `VB737373/Cursor`
5. **Deploy**

Готово. Vercel будет вызывать `/api/trigger` каждые 15 мин → GitHub Actions → Telegram.

### 3. Проверка
Vercel → Project → **Cron Jobs** — должно быть `*/15 * * * *`  
Через 15 мин: новый run на https://github.com/VB737373/Cursor/actions

---

Компьютер **не нужен**. Бесплатный тариф Vercel Hobby достаточен.
