<?php
declare(strict_types=1);
require __DIR__ . '/../php/common.php';

try {
    $config = radar_config();
    $route = (string) ($_GET['route'] ?? '');
    $method = (string) ($_SERVER['REQUEST_METHOD'] ?? 'GET');
    session_name('radar_admin');
    session_set_cookie_params([
        'lifetime' => 0, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax',
        'secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off'
    ]);
    session_start();
    $admin = !empty($_SESSION['admin']);

    if ($route === 'state' && $method === 'GET') radar_json(200, radar_public_state(radar_read_state(), $config, $admin));
    if ($route === 'auth' && $method === 'GET') radar_json(200, ['admin' => $admin, 'csrfToken' => $admin ? ($_SESSION['csrf'] ?? '') : '']);

    if ($route === 'login' && $method === 'POST') {
        if (empty($_SERVER['HTTPS']) || $_SERVER['HTTPS'] === 'off') radar_json(400, ['error' => 'Откройте сайт по HTTPS']);
        $input = radar_input();
        $password = (string) ($input['password'] ?? '');
        $ip = (string) ($_SERVER['REMOTE_ADDR'] ?? 'unknown');
        $key = hash_hmac('sha256', $ip, (string) ($config['admin_password'] ?? ''));
        $attempts = array_values(array_filter(radar_read_state()['loginFailures'][$key] ?? [], fn($time) => $time > time() - 900));
        if (count($attempts) >= 5) radar_json(429, ['error' => 'Слишком много попыток входа. Повторите через 15 минут.']);
        if (empty($config['admin_password']) || !hash_equals((string) $config['admin_password'], $password)) {
            radar_update_state(function (array &$state) use ($key): void {
                $times = array_values(array_filter($state['loginFailures'][$key] ?? [], fn($time) => $time > time() - 900));
                $times[] = time(); $state['loginFailures'][$key] = $times;
            });
            radar_json(401, ['error' => 'Неверный пароль']);
        }
        radar_update_state(function (array &$state) use ($key): void { unset($state['loginFailures'][$key]); });
        session_regenerate_id(true);
        $_SESSION['admin'] = true;
        $_SESSION['csrf'] = bin2hex(random_bytes(32));
        radar_json(200, ['admin' => true, 'csrfToken' => $_SESSION['csrf']]);
    }

    if ($method === 'POST') {
        if (!$admin) radar_json(401, ['error' => 'Для изменения данных войдите как администратор']);
        $csrf = (string) ($_SERVER['HTTP_X_CSRF_TOKEN'] ?? '');
        if (!$csrf || !hash_equals((string) ($_SESSION['csrf'] ?? ''), $csrf)) radar_json(403, ['error' => 'Сеанс устарел. Войдите ещё раз.']);
    }
    if ($route === 'logout' && $method === 'POST') {
        $_SESSION = []; session_destroy(); radar_json(200, ['ok' => true]);
    }
    if ($route === 'import' && $method === 'POST') {
        $payload = radar_input();
        $rows = array_is_list($payload) ? $payload : [$payload];
        if (count($rows) > 500) throw new InvalidArgumentException('Максимум 500 записей за раз');
        $valid = array_map('radar_valid_item', $rows);
        radar_update_state(function (array &$state) use ($valid): void {
            array_push($state['items'], ...$valid);
            $state['lastUpdated'] = radar_now();
        });
        radar_json(200, ['added' => count($valid)]);
    }
    if ($route === 'settings' && $method === 'POST') {
        $input = radar_input();
        $region = strtoupper(trim((string) ($input['region'] ?? 'RU')));
        $query = trim((string) ($input['query'] ?? ''));
        if (!preg_match('/^[A-Z]{2}$/', $region) || $query === '' || mb_strlen($query) > 80) throw new InvalidArgumentException('Укажите регион из двух букв и тему до 80 символов');
        radar_update_state(function (array &$state) use ($region, $query): void { $state['settings'] = ['region' => $region, 'query' => $query]; });
        radar_json(200, ['region' => $region, 'query' => $query]);
    }
    if ($route === 'sync' && $method === 'POST') {
        require __DIR__ . '/../php/collect.php';
        radar_json(200, radar_collect($config, true));
    }
    if ($route === 'webhook' && $method === 'POST') {
        require __DIR__ . '/../php/telegram.php';
        $site = rtrim((string) ($config['site_url'] ?? ''), '/');
        $secret = (string) ($config['telegram_webhook_secret'] ?? '');
        if (!preg_match('~^https://[^/]+$~', $site) || !preg_match('/^[A-Za-z0-9_-]{16,256}$/', $secret)) throw new InvalidArgumentException('Сначала укажите HTTPS-адрес сайта и секрет webhook в закрытом файле настроек');
        radar_telegram_api($config, 'setWebhook', [
            'url' => $site . '/telegram.php', 'secret_token' => $secret,
            'allowed_updates' => ['message'], 'drop_pending_updates' => false
        ]);
        radar_json(200, ['ok' => true]);
    }
    radar_json(404, ['error' => 'Не найдено']);
} catch (InvalidArgumentException $error) {
    radar_json(400, ['error' => $error->getMessage()]);
} catch (RadarHttpException $error) {
    radar_json($error->status, ['error' => $error->getMessage()]);
} catch (Throwable $error) {
    error_log('Trend Radar API: ' . $error->getMessage());
    radar_json(500, ['error' => 'Ошибка сервера. Проверьте журнал ошибок.']);
}

function radar_valid_item(mixed $input): array {
    if (!is_array($input) || !in_array($input['platform'] ?? null, ['YouTube', 'TikTok', 'Instagram', 'Threads'], true)) throw new InvalidArgumentException('Укажите платформу');
    $title = trim((string) ($input['title'] ?? ''));
    $url = (string) ($input['url'] ?? '');
    $views = $input['views'] ?? null;
    $published = strtotime((string) ($input['publishedAt'] ?? ''));
    if ($title === '' || !filter_var($url, FILTER_VALIDATE_URL) || !str_starts_with($url, 'https://') || !is_numeric($views) || (float) $views < 0 || $published === false) throw new InvalidArgumentException('Нужны название, ссылка HTTPS, просмотры и дата публикации');
    $metric = function (string $name) use ($input): ?int {
        $value = $input[$name] ?? null;
        if ($value === null || $value === '') return null;
        if (!is_numeric($value) || (float) $value < 0) throw new InvalidArgumentException('Метрики должны быть неотрицательными');
        return (int) $value;
    };
    return [
        'id' => bin2hex(random_bytes(16)), 'platform' => $input['platform'],
        'title' => mb_substr($title, 0, 180), 'creator' => mb_substr((string) ($input['creator'] ?? ''), 0, 90),
        'url' => $url, 'topic' => mb_substr((string) (($input['topic'] ?? '') ?: 'Онлайн-обучение'), 0, 80),
        'format' => mb_substr((string) (($input['format'] ?? '') ?: 'Короткое видео'), 0, 80),
        'views' => (int) $views, 'likes' => $metric('likes') ?? 0, 'comments' => $metric('comments') ?? 0,
        'shares' => $metric('shares'), 'reach' => $metric('reach'),
        'publishedAt' => gmdate('Y-m-d\TH:i:s\Z', $published), 'collectedAt' => radar_now(), 'source' => 'manual'
    ];
}
