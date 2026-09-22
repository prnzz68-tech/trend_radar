<?php
declare(strict_types=1);
require __DIR__ . '/../php/telegram.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(405); exit; }
try {
    $config = radar_config();
    $expected = (string) ($config['telegram_webhook_secret'] ?? '');
    $provided = (string) ($_SERVER['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'] ?? '');
    if ($expected === '' || !hash_equals($expected, $provided)) { http_response_code(403); exit; }
    $update = radar_input();
    radar_handle_telegram($config, $update);
    http_response_code(200);
    echo 'ok';
} catch (Throwable $error) {
    error_log('Trend Radar webhook: ' . $error->getMessage());
    http_response_code(500);
    echo 'error';
}
