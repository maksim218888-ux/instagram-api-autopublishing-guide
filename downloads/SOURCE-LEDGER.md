# Официальные источники

Проверено: 13 ноября 2026 года. Все текущие платформенные утверждения в наборе опираются на официальную документацию Meta.

## Главные страницы
- https://developers.facebook.com/documentation/instagram-platform/overview
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/authentication
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/permissions
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/eligibility-and-troubleshooting
- https://developers.facebook.com/documentation/instagram-platform/content-publishing
- https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads
- https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container
- https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media
- https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish
- https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit
- https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media
- https://developers.facebook.com/documentation/instagram-platform/app-review
- https://developers.facebook.com/documentation/instagram-platform/webhooks
- https://developers.facebook.com/documentation/instagram-platform/webhooks/setup
- https://developers.facebook.com/documentation/instagram-platform/changelog
- https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes

## Два числа, которые нельзя вшивать в код

1. **Публикации за 24 часа.** Одна официальная страница говорит о 100 API-публикациях, другой блок и reference endpoint показывают 50. Код должен читать `content_publishing_limit` на целевом аккаунте и оставлять резерв.
2. **Размер карусели.** Основные страницы описывают до 20 элементов, а одна официальная запись error codes всё ещё говорит о диапазоне 2–10. Проверяйте фактический предел на нужной версии API и аккаунте до production.

Полный внутренний claim ledger с локальными снимками и SHA-256 находится в проекте, но в ZIP не включены тяжёлые raw-снимки документации.
