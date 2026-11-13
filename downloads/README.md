# Instagram API autopublishing starter pack

Этот набор передают ИИ-агенту вместе с готовым медиафайлом, подписью и ответами владельца. По умолчанию он умеет только проверить материалы и собрать неизменяемую карточку запуска. Реальная публикация заперта отдельным флагом и точным `approval_hash`.

## Начните здесь
1. Откройте `ACCOUNT-READINESS.md` и ответьте на вопросы.
2. Скопируйте `config.example.json` в `config.json`; укажите локальные пути и временные HTTPS URL.
3. Никогда не вписывайте токен в JSON. Он читается только из `IG_ACCESS_TOKEN`.
4. Запустите:

```bash
python instagram_publish_agent.py check --config config.json
python instagram_publish_agent.py plan --config config.json --output approval-plan.json
```

5. Проверьте план и подтвердите точный hash.
6. Live publish выполняется только в отдельно подготовленной среде после прохождения `FINAL-QA-CHECKLIST.md`.

## Что внутри
- `AGENT-INSTRUCTIONS.md` — полный безопасный порядок.
- `MASTER-PROMPT.md` — текст, который можно передать агенту.
- `ACCOUNT-READINESS.md` — короткий опрос владельца.
- `instagram_publish_agent.py` — `check`/`plan` и guarded reference publish для одиночных изображений и Reels. Карусельная сборка описана в `STATE-MACHINE.md`, но намеренно не спрятана за непроверенной универсальной командой.
- `test_instagram_publish_agent.py` — smoke/unit tests без публикации.
- `config.schema.json`, `config.example.json`, `.env.example` — контракты конфигурации.
- `STATE-MACHINE.md` — состояния и duplicate guard.
- `TROUBLESHOOTING.md` — карта восстановления.
- `EXPECTED-OUTPUTS.md` — как выглядит нормальный результат.
- `FINAL-QA-CHECKLIST.md` — последняя проверка.
- `SOURCE-LEDGER.md` — официальные источники и важные противоречия.

## Граница ответственности
Код не создаёт Meta app, не проходит App Review, не выдаёт права и не гарантирует доступность Trial. Это нужно настроить и проверить на целевом аккаунте. Набор не выполняет live публикацию во время тестов.
