<?php
declare(strict_types=1);
require_once __DIR__ . '/common.php';

function radar_telegram_api(array $config, string $method, array $payload): mixed {
    if (empty($config['telegram_token'])) throw new RuntimeException('Токен Telegram не настроен');
    $blocked = radar_read_state()['telegramBlockedUntil'] ?? null;
    if ($blocked && radar_ms((string) $blocked) > time() * 1000) throw new RadarHttpException('Telegram временно ограничил отправку', 429);
    if ($method === 'sendMessage') {
        $wait = radar_update_state(function (array &$state): float {
            $now = microtime(true);
            $start = max($now, (float) ($state['telegramNextSendAt'] ?? 0));
            $state['telegramNextSendAt'] = $start + 1;
            return $start - $now;
        });
        if ($wait > 0) usleep((int) ($wait * 1000000));
    }
    $curl = curl_init('https://api.telegram.org/bot' . $config['telegram_token'] . '/' . $method);
    curl_setopt_array($curl, [
        CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR),
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'], CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => 20
    ]);
    $body = curl_exec($curl);
    $status = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
    $networkError = curl_error($curl);
    curl_close($curl);
    $result = is_string($body) ? json_decode($body, true) : null;
    if ($status >= 200 && $status < 300 && !empty($result['ok'])) return $result['result'] ?? [];
    $retry = max(0, (int) ($result['parameters']['retry_after'] ?? 0));
    if ($retry) radar_update_state(function (array &$state) use ($retry): void { $state['telegramBlockedUntil'] = gmdate('Y-m-d\TH:i:s\Z', time() + $retry); });
    throw new RadarHttpException('Telegram: ' . ($result['description'] ?? ($networkError ?: "HTTP $status")), $status ?: 502);
}

function radar_telegram_send(array $config, string $chat, string $text): void {
    radar_telegram_api($config, 'sendMessage', ['chat_id' => $chat, 'text' => mb_substr($text, 0, 4000)]);
}

function radar_digest_text(array $snapshot): ?string {
    $top = array_values(array_filter($snapshot['top'] ?? [], fn($item) => str_starts_with((string) ($item['url'] ?? ''), 'https://')));
    if (!$top) return null;
    $lines = ['Тренд радар · ' . $snapshot['settings']['query'], '', 'Топ видео сегодня:'];
    foreach (array_slice($top, 0, 3) as $index => $item) {
        $views = max(1, (int) ($item['views'] ?? 0));
        $rate = ((int) ($item['likes'] ?? 0) + (int) ($item['comments'] ?? 0)) / $views;
        array_push($lines, '', ($index + 1) . '. ' . $item['platform'] . ' · ' . mb_substr($item['title'], 0, 120),
            number_format((int) $item['views'], 0, ',', ' ') . ' просмотров · ' . number_format($rate * 100, 1, ',', '') . '% реакций', $item['url']);
    }
    $leader = $top[0]; $engaged = $top[0];
    $reactionRate = fn($item) => ((int) ($item['likes'] ?? 0) + (int) ($item['comments'] ?? 0)) / max(1, (int) ($item['views'] ?? 0));
    foreach ($top as $item) {
        if ((int) $item['views'] > (int) $leader['views']) $leader = $item;
        if ($reactionRate($item) > $reactionRate($engaged)) $engaged = $item;
    }
    $views = array_map(fn($item) => (int) $item['views'], $snapshot['items'] ?? $top);
    sort($views, SORT_NUMERIC);
    $middle = intdiv(count($views), 2);
    $median = !$views ? 0 : (count($views) % 2 ? $views[$middle] : ($views[$middle - 1] + $views[$middle]) / 2);
    $comparison = $median > 0 ? number_format((int) $leader['views'] / $median, 1, ',', '') . ' раза от медианы ' . count($views) . ' видео' : 'медиана равна нулю';
    $first = preg_match('/егэ/iu', $leader['title'])
        ? 'Покажите ошибку в задании ЕГЭ, её решение и предложите диагностику знаний или пробный урок курса.'
        : 'Покажите результат ученика в первые секунды, затем фрагмент урока и приглашение на курс.';
    $second = preg_match('/егэ/iu', $engaged['title'])
        ? 'Второй вариант — ответ преподавателя на вопрос по заданию ЕГЭ и приглашение на курс подготовки.'
        : 'Второй вариант — короткий ответ преподавателя на вопрос ученика.';
    array_push($lines, '', 'Гипотеза для рекламы:',
        'Лидер набрал ' . number_format((int) $leader['views'], 0, ',', ' ') . " просмотров; $comparison. Лучший отклик в топ-3 у «" . mb_substr($engaged['title'], 0, 70) . '».',
        $first, $second,
        'Покажите оба варианта одной аудитории с равным бюджетом 3 дня. Сравните заявки и их стоимость.');
    return implode("\n", $lines);
}

function radar_global_text(array $snapshot): string {
    $top = $snapshot['globalTop'] ?? [];
    if (!$top) return 'Глобальных видео пока нет. Обновите данные в панели.';
    $lines = ['Глобальные тренды · топ-3 по просмотрам', 'Короткие YouTube видео за 7 дней без тематического фильтра.'];
    foreach ($top as $index => $item) array_push($lines, '', ($index + 1) . '. ' . $item['platform'] . ' · ' . mb_substr($item['title'], 0, 120),
        number_format((int) $item['views'], 0, ',', ' ') . ' просмотров', $item['url']);
    return implode("\n", $lines);
}

function radar_handle_telegram(array $config, array $update): void {
    $updateId = (int) ($update['update_id'] ?? 0);
    $message = $update['message'] ?? null;
    if (!$updateId || !is_array($message) || empty($message['chat']['id']) || !is_string($message['text'] ?? null)) return;
    $chat = (string) $message['chat']['id'];
    $command = strtolower(explode('@', preg_split('/\s+/', trim($message['text']))[0])[0]);
    if (!in_array($command, ['/start', '/help', '/stop', '/digest', '/global', '/status'], true)) return;
    $accepted = radar_update_state(function (array &$state) use ($updateId, $chat, $command, $message): bool {
        if ($updateId <= (int) ($state['telegramLastUpdateId'] ?? 0)) return false;
        $cooldowns = array_filter($state['telegramCooldowns'] ?? [], fn($time) => $time > time() - 86400);
        $key = "$chat:$command";
        $recent = (int) ($cooldowns[$key] ?? 0);
        if ($recent > time() - 30) return false;
        if ($command === '/start' && ($message['chat']['type'] ?? '') === 'private') {
            if (!in_array($chat, $state['telegramSubscribers'], true)) $state['telegramSubscribers'][] = $chat;
        }
        if ($command === '/stop') $state['telegramSubscribers'] = array_values(array_filter($state['telegramSubscribers'], fn($id) => (string) $id !== $chat));
        return true;
    });
    if (!$accepted) return;
    $snapshot = radar_public_state(radar_read_state(), $config);
    $reply = match ($command) {
        '/start' => 'Тренд радар подключён.' . (($message['chat']['type'] ?? '') === 'private' ? ' Ежедневная подборка включена.' : '') . ' /digest — темы, /global — глобальные видео, /status — состояние, /stop — отписка.',
        '/help' => '/start — включить ежедневную подборку; /digest — онлайн-обучение и ЕГЭ; /global — глобальные тренды; /status — состояние; /stop — отписка.',
        '/stop' => 'Ежедневная подборка отключена. Команды /digest и /global доступны. Для подписки отправьте /start.',
        '/digest' => radar_digest_text($snapshot) ?: 'Пока нет реальных видео со ссылками. Обновите YouTube или добавьте ролики вручную.',
        '/global' => radar_global_text($snapshot),
        '/status' => 'Видео по темам: ' . $snapshot['count'] . "\nГлобальные сигналы: " . $snapshot['globalCount'] . "\nYouTube: " . ($snapshot['hasYouTubeKey'] ? 'подключён' : 'нет ключа'),
    };
    radar_telegram_send($config, $chat, $reply);
    radar_update_state(function (array &$state) use ($updateId, $chat, $command): void {
        $state['telegramLastUpdateId'] = max($updateId, (int) ($state['telegramLastUpdateId'] ?? 0));
        $state['telegramCooldowns']["$chat:$command"] = time();
    });
}

function radar_send_daily(array $config): void {
    if (empty($config['telegram_token'])) return;
    $zone = new DateTimeZone('Europe/Moscow');
    $date = new DateTimeImmutable('now', $zone);
    $hour = (int) ($config['telegram_digest_hour'] ?? 9);
    if ((int) $date->format('G') < $hour) return;
    $day = $date->format('Y-m-d');
    $state = radar_read_state();
    $snapshot = radar_public_state($state, $config);
    $text = radar_digest_text($snapshot);
    if (!$text) return;
    foreach ($state['telegramSubscribers'] as $chat) {
        if (($state['telegramLastSentByChat'][(string) $chat] ?? null) === $day) continue;
        try {
            radar_telegram_send($config, (string) $chat, $text);
            radar_update_state(function (array &$saved) use ($chat, $day): void {
                $saved['telegramLastSentByChat'][(string) $chat] = $day;
                $saved['telegramLastSentDate'] = $day;
            });
        } catch (RadarHttpException $error) {
            error_log('Trend Radar Telegram: ' . $error->getMessage());
            if (in_array($error->status, [400, 403], true)) radar_update_state(function (array &$saved) use ($chat): void {
                $saved['telegramSubscribers'] = array_values(array_filter($saved['telegramSubscribers'], fn($id) => (string) $id !== (string) $chat));
            });
            if ($error->status === 429) break;
        }
    }
}
