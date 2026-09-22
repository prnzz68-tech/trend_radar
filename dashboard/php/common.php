<?php
declare(strict_types=1);

const RADAR_ROOT = __DIR__ . '/..';
class RadarHttpException extends RuntimeException {
    public function __construct(string $message, public int $status = 400) { parent::__construct($message); }
}

function radar_config(): array {
    $file = __DIR__ . '/config.local.php';
    if (!is_file($file)) throw new RuntimeException('Создайте закрытый файл php/config.local.php по образцу config.example.php');
    $config = require $file;
    if (!is_array($config)) throw new RuntimeException('Неверный файл конфигурации');
    return $config;
}

function radar_data_file(): string {
    return RADAR_ROOT . '/data/radar.json';
}

function radar_default_state(): array {
    return [
        'settings' => ['region' => 'RU', 'query' => 'онлайн обучение и курсы ЕГЭ'],
        'items' => [], 'globalItems' => [], 'lastSync' => null, 'globalLastSync' => null,
        'lastManualSyncAt' => null, 'youtubeBlockedUntil' => null, 'lastUpdated' => null,
        'syncError' => null, 'globalSyncError' => null, 'telegramSubscribers' => [],
        'telegramLastSentByChat' => [], 'telegramLastSentDate' => null,
        'telegramLegacyMigrated' => true, 'telegramLastUpdateId' => 0, 'loginFailures' => []
    ];
}

function radar_read_state(): array {
    $file = radar_data_file();
    if (!is_file($file)) return radar_default_state();
    $decoded = json_decode((string) file_get_contents($file), true);
    if (!is_array($decoded)) throw new RuntimeException('Не удалось прочитать данные радара');
    return array_replace(radar_default_state(), $decoded);
}

function radar_update_state(callable $change): mixed {
    $dir = dirname(radar_data_file());
    if (!is_dir($dir) && !mkdir($dir, 0700, true) && !is_dir($dir)) throw new RuntimeException('Не удалось создать каталог данных');
    $lock = fopen($dir . '/.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX)) throw new RuntimeException('Не удалось заблокировать данные');
    try {
        $state = radar_read_state();
        $result = $change($state);
        $tmp = $dir . '/.radar-' . bin2hex(random_bytes(8));
        $json = json_encode($state, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR);
        if (file_put_contents($tmp, $json, LOCK_EX) === false || !rename($tmp, radar_data_file())) {
            @unlink($tmp);
            throw new RuntimeException('Не удалось сохранить данные');
        }
        @chmod(radar_data_file(), 0600);
        return $result;
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

function radar_now(): string { return gmdate('Y-m-d\TH:i:s\Z'); }
function radar_ms(string $date): int { $time = strtotime($date); return $time === false ? 0 : $time * 1000; }

function radar_score(array $item): float {
    $age = max(1, (time() - (strtotime((string) ($item['publishedAt'] ?? '')) ?: time())) / 3600);
    $views = max(0, (float) ($item['views'] ?? 0));
    $engagement = ((float) ($item['likes'] ?? 0) + 2 * (float) ($item['comments'] ?? 0) + 3 * (float) ($item['shares'] ?? 0)) / max(1, $views);
    return ($views / pow($age + 6, .72)) * (1 + min($engagement, .25) * 3);
}

function radar_top_three(array $ranked, string $query): array {
    $selected = []; $creators = [];
    if ($query === 'онлайн обучение и курсы ЕГЭ') {
        $online = null; $ege = null;
        foreach ($ranked as $item) if (($item['topic'] ?? '') !== 'Курсы подготовки к ЕГЭ') { $online = $item; break; }
        foreach ($ranked as $item) if (($item['topic'] ?? '') === 'Курсы подготовки к ЕГЭ' && ($item['creator'] ?? '') !== ($online['creator'] ?? null)) { $ege = $item; break; }
        foreach ([$online, $ege] as $item) if ($item) { $selected[] = $item; $creators[mb_strtolower(trim((string) ($item['creator'] ?: $item['id'])))] = true; }
    }
    foreach ($ranked as $item) {
        $creator = mb_strtolower(trim((string) (($item['creator'] ?? '') ?: $item['id'])));
        if (isset($creators[$creator])) continue;
        $selected[] = $item; $creators[$creator] = true;
        if (count($selected) === 3) break;
    }
    foreach ($ranked as $item) {
        if (count($selected) === 3) break;
        if (!in_array($item, $selected, true)) $selected[] = $item;
    }
    usort($selected, fn($a, $b) => radar_score($b) <=> radar_score($a));
    return $selected;
}

function radar_public_state(array $state, array $config, bool $admin = false): array {
    $items = $state['items'] ?? [];
    usort($items, fn($a, $b) => radar_score($b) <=> radar_score($a));
    $recentManual = array_values(array_filter($items, fn($item) => ($item['source'] ?? '') === 'manual' && (strtotime((string) ($item['publishedAt'] ?? '')) ?: 0) >= time() - 7 * 86400));
    $global = array_values(array_filter(array_merge($state['globalItems'] ?? [], $recentManual), fn($item) => !empty($item['url'])));
    usort($global, fn($a, $b) => ((float) ($b['views'] ?? 0)) <=> ((float) ($a['views'] ?? 0)));
    return [
        'settings' => $state['settings'], 'lastSync' => $state['lastSync'], 'lastUpdated' => $state['lastUpdated'],
        'syncError' => $state['syncError'], 'demo' => false, 'hasYouTubeKey' => !empty($config['youtube_key']),
        'telegramConfigured' => !empty($config['telegram_token']), 'telegramLinked' => count($state['telegramSubscribers'] ?? []) > 0,
        'telegramSubscriberCount' => count($state['telegramSubscribers'] ?? []), 'telegramLastSentDate' => $state['telegramLastSentDate'],
        'count' => count($items), 'top' => array_map(fn($item) => $item + ['trendScore' => round(radar_score($item))], radar_top_three($items, (string) $state['settings']['query'])),
        'items' => array_map(fn($item) => $item + ['trendScore' => round(radar_score($item))], $items),
        'globalCount' => count($global), 'globalTop' => array_slice($global, 0, 3),
        'globalLastSync' => $state['globalLastSync'], 'globalSyncError' => $state['globalSyncError'],
        'lastManualSyncAt' => $state['lastManualSyncAt'], 'youtubeBlockedUntil' => $state['youtubeBlockedUntil'],
        'authRequired' => true, 'isAdmin' => $admin
    ];
}

function radar_json(int $status, array $payload): never {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    exit;
}

function radar_input(): array {
    $raw = file_get_contents('php://input', false, null, 0, 2000001);
    if ($raw === false || strlen($raw) > 2000000) throw new InvalidArgumentException('Слишком большой запрос');
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) throw new InvalidArgumentException('Ожидаются данные JSON');
    return $decoded;
}
