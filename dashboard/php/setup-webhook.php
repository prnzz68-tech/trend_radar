<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') exit(1);
require __DIR__ . '/telegram.php';
$config = radar_config();
$site = rtrim((string) ($config['site_url'] ?? ''), '/');
$secret = (string) ($config['telegram_webhook_secret'] ?? '');
if (!preg_match('~^https://[^/]+$~', $site) || !preg_match('/^[A-Za-z0-9_-]{16,256}$/', $secret)) {
    throw new RuntimeException('Укажите HTTPS site_url и случайный telegram_webhook_secret из 16–256 символов');
}
radar_telegram_api($config, 'setWebhook', [
    'url' => $site . '/telegram.php', 'secret_token' => $secret,
    'allowed_updates' => ['message'], 'drop_pending_updates' => false
]);
echo "Telegram webhook configured for $site\n";
