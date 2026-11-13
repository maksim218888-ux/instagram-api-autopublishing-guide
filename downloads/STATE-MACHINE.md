# Состояния публикации и защита от дублей

```text
DRAFT
  → PREFLIGHT_PASSED
  → PLAN_FROZEN
  → OWNER_CONFIRMED
  → ACCOUNT_VERIFIED
  → CONTAINER_CREATED
  → CONTAINER_IN_PROGRESS
  → CONTAINER_FINISHED
  → PUBLISH_REQUEST_STARTED
  → PUBLISH_RESPONSE_RECEIVED
  → READBACK_VERIFIED
  → TEMP_ASSET_REVOKED
  → COMPLETE
```

Остановочные состояния:

```text
PREFLIGHT_FAILED
ACCOUNT_MISMATCH
CONTAINER_ERROR
CONTAINER_EXPIRED
POLL_TIMEOUT
PUBLISH_UNKNOWN
READBACK_MISMATCH
RECONCILE_REQUIRED
```

## Ключ одного запуска

`approval_hash = SHA256(account_id + username + media SHA256 + caption SHA256 + cover SHA256 + mode + trial strategy + flags)`

У одного hash один журнал и не больше одной попытки publish. Изменился файл, текст, аккаунт, режим или флаг — появился новый hash, а значит, нужно новое подтверждение.

## Самая опасная ситуация: ответ потерялся

Если связь оборвалась после начала `media_publish`, это не «ошибка, попробуем ещё раз». Состояние становится `PUBLISH_UNKNOWN`.

Дальше агент:
1. читает статус того же container ID;
2. проверяет последние media нужного аккаунта;
3. сопоставляет время, подпись, тип материала и @username;
4. записывает `PUBLISHED` или `RECONCILE_REQUIRED`.

Пока сверка не закончена, второй publish запрещён.

## Правила очереди
- уникальный индекс по `approval_hash`;
- один worker держит lease/lock;
- heartbeat показывает, что worker жив;
- автоматические повторы допустимы только до границы publish;
- спорные задачи уходят в dead-letter queue и требуют человека;
- время хранится как UTC плюс исходный часовой пояс;
- утверждённый payload неизменяем;
- журнал дописывается событиями, а не переписывает прошлое.
