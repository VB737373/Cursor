# Запуск бота 24/7 бесплатно на Oracle Cloud

Цель: бот работает круглосуточно на бесплатном сервере, **компьютер можно выключать**.
Сервер за границей — Telegram и Hyperliquid открываются **без VPN**.

Всё бесплатно навсегда (Oracle "Always Free"). При регистрации спросят банковскую
карту только для проверки личности — деньги не списываются.

---

## Шаг 1. Регистрация на Oracle Cloud

1. Открой https://www.oracle.com/cloud/free/ → **Start for free**.
2. Заполни данные, подтверди email и телефон.
3. Привяжи банковскую карту (проверка личности, списаний нет).
4. **Home Region** выбери европейский, например **Germany Central (Frankfurt)** или
   **Netherlands Northwest (Amsterdam)** — регион потом не поменять, поэтому важно.

---

## Шаг 2. Создание бесплатного сервера (VM)

1. В панели: меню ☰ → **Compute** → **Instances** → **Create instance**.
2. **Image and shape** → **Edit**:
   - Image: **Canonical Ubuntu 22.04**.
   - Shape: выбери **Always Free eligible**:
     - лучше всего **VM.Standard.A1.Flex** (ARM), поставь 1 OCPU и 6 ГБ RAM;
     - если пишет "out of capacity" — возьми **VM.Standard.E2.1.Micro** (тоже бесплатный).
3. **SSH keys**: выбери **Generate a key pair for me** → нажми
   **Save private key** (скачается файл вида `ssh-key-XXXX.key`) — сохрани его,
   он нужен для входа.
4. Жми **Create**. Через 1–2 минуты статус станет **RUNNING**.
5. Запиши **Public IP address** сервера (на странице инстанса).

---

## Шаг 3. Вход на сервер по SSH (с Windows)

1. Открой **PowerShell** в папке, куда скачал ключ (например, `Downloads`).
2. Разово поправь права на ключ (иначе SSH ругается):

```powershell
icacls "ssh-key-XXXX.key" /inheritance:r
icacls "ssh-key-XXXX.key" /grant:r "$($env:USERNAME):(R)"
```

3. Подключись (подставь свой IP):

```powershell
ssh -i "ssh-key-XXXX.key" ubuntu@ВАШ_IP
```

На вопрос "Are you sure...?" введи `yes`. Ты на сервере.

---

## Шаг 4. Загрузка файлов бота на сервер

**На своём компьютере** (в PowerShell, из папки проекта `C:\Users\Admin\Desktop\Cursor`)
собери архив только с нужными файлами:

```powershell
cd C:\Users\Admin\Desktop\Cursor
$items = 'bot.py','config.py','indicators.py','journal.py','requirements.txt',
         'whales.txt','.env','subscribers.json','trades.json','engine','sources','deploy'
Compress-Archive -Path $items -DestinationPath crypto-bot.zip -Force
```

Отправь архив на сервер (подставь свой ключ и IP):

```powershell
scp -i "ssh-key-XXXX.key" crypto-bot.zip ubuntu@ВАШ_IP:~/
```

---

## Шаг 5. Установка и запуск (на сервере)

Вернись в SSH-сессию сервера и выполни:

```bash
sudo apt-get update -y && sudo apt-get install -y unzip dos2unix
mkdir -p ~/crypto-bot
unzip -o ~/crypto-bot.zip -d ~/crypto-bot
cd ~/crypto-bot
dos2unix deploy/setup.sh deploy/crypto-signals.service    # убрать Windows-переносы строк
bash deploy/setup.sh
```

Скрипт сам поставит Python, зависимости и настроит автозапуск.
В конце покажет статус — должно быть `active (running)`.

---

## Готово

Бот работает круглосуточно, перезапускается сам при сбоях и после перезагрузки
сервера. Компьютер можно выключать.

### Полезные команды (на сервере)

```bash
sudo journalctl -u crypto-signals -f      # смотреть логи в реальном времени
sudo systemctl status crypto-signals      # статус
sudo systemctl restart crypto-signals     # перезапустить
sudo systemctl stop crypto-signals        # остановить
```

### Как обновить код позже

1. На ПК пересобери `crypto-bot.zip` (Шаг 4) и залей через `scp` (перезапишет архив).
2. На сервере:

```bash
unzip -o ~/crypto-bot.zip -d ~/crypto-bot
sudo systemctl restart crypto-signals
```

### Важно
- Перед отправкой убедись, что на **этом** компьютере бот **остановлен** (иначе два
  бота с одним токеном дадут ошибку `409 Conflict`). После переезда на сервер
  локально запускать бота больше не нужно.
- Файл `.env` содержит токен бота — не выкладывай архив в открытый доступ.
