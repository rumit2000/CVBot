# Запуск CVBot на VPS через Docker

Эта схема запускает `polling_worker.py` в отдельном контейнере. Секреты остаются
в `/etc/cvbot/cvbot.env` на VPS и не попадают ни в Git, ни в Docker-образ.
Health endpoint публикуется только на loopback VPS: `127.0.0.1:10000`.

## Важное перед запуском

Одновременно должен работать только один экземпляр Telegram long polling.
Сначала можно собрать образ и создать контейнер, но `systemctl start cvbot`
выполняйте только после остановки сервиса на Render. Иначе Telegram будет
возвращать конфликт `409`.

Команды ниже ничего не удаляют. Создание контейнера специально завершится
ошибкой, если контейнер с именем `cvbot` уже существует. Для его удаления или
замены нужно отдельное явное решение владельца.

## 1. Подготовить код и образ

На VPS перейдите в уже загруженную копию репозитория:

```bash
cd /opt/CVBot
sudo docker build --tag cvbot:local .
```

## 2. Создать защищённый env-файл

```bash
sudo install -d -m 700 /etc/cvbot
sudo test ! -e /etc/cvbot/cvbot.env && sudo install -m 600 /dev/null /etc/cvbot/cvbot.env
sudoedit /etc/cvbot/cvbot.env
```

Если проверка `test` вернула ошибку, файл уже существует: остановитесь и
сначала проверьте его, не заменяя. Команда `install` создаёт новый пустой файл
с правами `600` только после успешной проверки.

Заполните файл реальными значениями непосредственно на VPS:

```dotenv
TELEGRAM_BOT_TOKEN=replace_me
OPENAI_API_KEY=replace_me
OWNER_ID=replace_me
OPENAI_MODEL=gpt-4o-mini
RESUME_PATH=data/CVTimurAsyaev.pdf
HEALTH_HOST=0.0.0.0
PORT=10000
LOG_LEVEL=INFO
```

`LINKEDIN_URL` и `CONTACT_INFO` можно добавить при необходимости. Не храните
этот env-файл в каталоге репозитория.

Внутри контейнера health-сервер слушает `0.0.0.0`, чтобы Docker мог передать
ему запрос. Публикация ниже привязана к `127.0.0.1`, поэтому снаружи VPS порт
недоступен.

## 3. Создать контейнер, пока Render ещё работает

Лимит памяти `384 MiB` оставляет запас другим сервисам VPS с 1 GiB RAM.
Логи Docker ограничены, а процесс работает без Linux capabilities и с
ограничением числа процессов.

```bash
sudo docker create \
  --name cvbot \
  --init \
  --stop-timeout 30 \
  --env-file /etc/cvbot/cvbot.env \
  --publish 127.0.0.1:10000:10000 \
  --memory 384m \
  --memory-swap 512m \
  --cpus 0.75 \
  --pids-limit 128 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --log-driver local \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --restart no \
  cvbot:local
```

Контейнер здесь только создаётся и ещё не запускается.

## 4. Установить unit systemd

```bash
sudo test ! -e /etc/systemd/system/cvbot.service && sudo install -m 644 /opt/CVBot/deploy/cvbot.service /etc/systemd/system/cvbot.service
sudo systemctl daemon-reload
sudo systemctl enable cvbot.service
```

Если первая проверка вернула ошибку, unit с таким именем уже есть: не
перезаписывайте его без отдельной проверки и согласования.

`enable` включает автозапуск после перезагрузки, но не запускает бота сейчас.

## 5. Переключить бота с Render на VPS

1. Остановите сервис на Render и отключите его автоматический деплой.
2. Убедитесь, что старый процесс больше не выполняет long polling.
3. Только после этого запустите контейнер на VPS:

```bash
sudo systemctl start cvbot.service
sudo systemctl status cvbot.service --no-pager
sudo docker logs --tail 100 cvbot
curl --fail --silent --show-error http://127.0.0.1:10000/healthz
```

Ожидаемый ответ health endpoint: `{"status":"ok"}`.

## Диагностика без изменения состояния

```bash
sudo systemctl status cvbot.service --no-pager
sudo docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' cvbot
sudo docker logs --tail 100 cvbot
curl --fail --silent --show-error http://127.0.0.1:10000/healthz
```

Для отката сначала остановите unit на VPS (`sudo systemctl stop cvbot`), а затем
снова запустите Render. Остановка не удаляет контейнер, образ или его данные.
